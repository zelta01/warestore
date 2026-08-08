# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 bet3rd

"""Windows DACL helpers for files consumed by the elevated application."""

from __future__ import annotations

import os


def is_reparse_point(path: str) -> bool:
    """Reject symlinks/junctions that could redirect a privileged file lookup."""
    if os.name != "nt":
        return os.path.islink(path)
    import ctypes

    get_attributes = ctypes.windll.kernel32.GetFileAttributesW
    get_attributes.argtypes = [ctypes.c_wchar_p]
    get_attributes.restype = ctypes.c_uint32
    attributes = get_attributes(path)
    return attributes != 0xFFFFFFFF and bool(attributes & 0x400)


def _security_parts():
    import ntsecuritycon
    import win32security

    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)
    administrators = win32security.CreateWellKnownSid(
        win32security.WinBuiltinAdministratorsSid
    )
    users = win32security.CreateWellKnownSid(win32security.WinBuiltinUsersSid)
    read_execute = ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_EXECUTE
    return win32security, ntsecuritycon, system, administrators, users, read_execute


def ensure_admin_only_dir(path: str) -> str:
    """Create ``path`` with a protected DACL.

    SYSTEM and Administrators receive full control; Users receive read/execute.
    The DACL is protected so permissive ACEs inherited from ``%PROGRAMDATA%`` do
    not survive. ACL failures propagate intentionally: privileged callers must
    fail closed instead of falling back to a user-writable directory.
    """
    if os.name != "nt":
        raise OSError("admin-only directories are supported only on Windows")

    os.makedirs(path, exist_ok=True)
    if is_reparse_point(path):
        raise OSError(f"privileged directory is a reparse point: {path}")
    win32security, ntsecuritycon, system, administrators, users, read_execute = (
        _security_parts()
    )
    inherit = (
        win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE
    )
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        inherit,
        ntsecuritycon.FILE_ALL_ACCESS,
        system,
    )
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        inherit,
        ntsecuritycon.FILE_ALL_ACCESS,
        administrators,
    )
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        inherit,
        read_execute,
        users,
    )
    security_info = (
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION
    )
    win32security.SetNamedSecurityInfo(
        path,
        win32security.SE_FILE_OBJECT,
        security_info,
        None,
        None,
        dacl,
        None,
    )
    if not is_admin_only_dir(path):
        raise PermissionError(f"failed to protect privileged directory: {path}")
    return path


def is_admin_only_dir(path: str) -> bool:
    """Return whether ``path`` has exactly the protected DACL we install."""
    if os.name != "nt" or not os.path.isdir(path) or is_reparse_point(path):
        return False
    try:
        win32security, ntsecuritycon, system, administrators, users, read_execute = (
            _security_parts()
        )
        descriptor = win32security.GetNamedSecurityInfo(
            path,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        control, _revision = descriptor.GetSecurityDescriptorControl()
        if not control & win32security.SE_DACL_PROTECTED:
            return False
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None or dacl.GetAceCount() != 3:
            return False

        expected = {
            win32security.ConvertSidToStringSid(system): ntsecuritycon.FILE_ALL_ACCESS,
            win32security.ConvertSidToStringSid(
                administrators
            ): ntsecuritycon.FILE_ALL_ACCESS,
            win32security.ConvertSidToStringSid(users): read_execute,
        }
        actual: dict[str, int] = {}
        for index in range(dacl.GetAceCount()):
            header, mask, sid = dacl.GetAce(index)
            if header[0] != win32security.ACCESS_ALLOWED_ACE_TYPE:
                return False
            actual[win32security.ConvertSidToStringSid(sid)] = mask
        return actual == expected
    except Exception:
        return False


def ensure_admin_only_file(path: str) -> str:
    """Apply the protected admin/SYSTEM-full, Users-read DACL to a file."""
    if os.name != "nt":
        raise OSError("admin-only files are supported only on Windows")
    if not os.path.isfile(path) or is_reparse_point(path):
        raise OSError(f"privileged file is missing or is a reparse point: {path}")

    win32security, ntsecuritycon, system, administrators, users, read_execute = (
        _security_parts()
    )
    dacl = win32security.ACL()
    for sid, mask in (
        (system, ntsecuritycon.FILE_ALL_ACCESS),
        (administrators, ntsecuritycon.FILE_ALL_ACCESS),
        (users, read_execute),
    ):
        dacl.AddAccessAllowedAceEx(win32security.ACL_REVISION_DS, 0, mask, sid)
    win32security.SetNamedSecurityInfo(
        path,
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        dacl,
        None,
    )
    if not is_admin_only_file(path):
        raise PermissionError(f"failed to protect privileged file: {path}")
    return path


def is_admin_only_file(path: str) -> bool:
    """Return whether a regular file has the protected DACL we install."""
    if os.name != "nt" or not os.path.isfile(path) or is_reparse_point(path):
        return False
    try:
        win32security, ntsecuritycon, system, administrators, users, read_execute = (
            _security_parts()
        )
        descriptor = win32security.GetNamedSecurityInfo(
            path,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        control, _revision = descriptor.GetSecurityDescriptorControl()
        if not control & win32security.SE_DACL_PROTECTED:
            return False
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None or dacl.GetAceCount() != 3:
            return False
        expected = {
            win32security.ConvertSidToStringSid(system): ntsecuritycon.FILE_ALL_ACCESS,
            win32security.ConvertSidToStringSid(
                administrators
            ): ntsecuritycon.FILE_ALL_ACCESS,
            win32security.ConvertSidToStringSid(users): read_execute,
        }
        actual: dict[str, int] = {}
        for index in range(dacl.GetAceCount()):
            header, mask, sid = dacl.GetAce(index)
            if header[0] != win32security.ACCESS_ALLOWED_ACE_TYPE:
                return False
            actual[win32security.ConvertSidToStringSid(sid)] = mask
        return actual == expected
    except Exception:
        return False
