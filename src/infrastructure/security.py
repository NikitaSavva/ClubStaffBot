import hashlib


class Sha256InviteTokenHasher:
    def hash(self, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
