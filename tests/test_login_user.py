from warestore.domain.steam.models import LoginUser
from warestore.domain.steam.services.login_service import SteamLoginService


def test_login_user_to_dict():
    user = LoginUser(
        steam_id="76561198000000001",
        account_name="alice",
        persona_name="Alice",
        timestamp=123,
        most_recent="1",
    )
    d = user.to_dict()
    assert d["steamid"] == "76561198000000001"
    assert d["account_name"] == "alice"
    assert d["most_recent"] == "1"


def test_parse_loginusers_returns_all_250_accounts(tmp_path):
    users = {
        str(76561198000000000 + index): {
            "AccountName": f"account-{index}",
            "PersonaName": f"Persona {index}",
            "Timestamp": str(index),
            "MostRecent": "0",
        }
        for index in range(250)
    }

    class Files:
        def read_vdf(self, _path):
            return {"users": users}

    path = tmp_path / "loginusers.vdf"
    path.touch()
    service = object.__new__(SteamLoginService)
    service._files = Files()

    accounts = service.parse_loginusers(str(path))

    assert len(accounts) == 250
    assert accounts[0].timestamp == 249
    assert accounts[-1].timestamp == 0
