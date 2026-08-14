from enum import StrEnum


class SupportedScopes(StrEnum):
    OPENID = "openid"
    PROFILE = "profile"
    EMAIL = "email"
    NETWORKS = "networks"
    AMR = "amr"
