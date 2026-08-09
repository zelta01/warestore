import os


def test_valvepython_client_loads_with_patched_protobuf():
    # Importing this module selects the compatibility backend before ValvePython
    # loads its older generated descriptors.
    from warestore.infrastructure.steam import cs2_cm_mint  # noqa: F401

    assert os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] == "python"

    from google.protobuf import __version__ as protobuf_version
    from steam.core.msg import MsgProto
    from steam.enums.emsg import EMsg

    assert tuple(map(int, protobuf_version.split(".")[:3])) >= (6, 33, 5)
    assert MsgProto(EMsg.ClientLogon).body is not None
