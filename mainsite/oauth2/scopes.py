from enum import Enum


class StrEnum(str, Enum):
    def __str__(self):
        return str(self.value)


class SupportedScopes(StrEnum):
    OPENID = "openid"
    PROFILE = "profile"
    EMAIL = "email"
    NETWORKS = "networks"
    AMR = "amr"
