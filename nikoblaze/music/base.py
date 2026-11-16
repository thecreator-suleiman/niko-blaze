"""Modular music-provider interface. Add new engines by subclassing Provider."""
from dataclasses import asdict, dataclass, field


@dataclass
class Job:
    song_id: str
    caption: str
    lyrics: str
    duration: float
    bpm: int
    keyscale: str
    seed: int
    instrumental: bool
    candidates: int = 2
    language: str = "en"

    def to_dict(self):
        return asdict(self)


@dataclass
class Capabilities:
    name: str
    male_vocals: str
    instrumentals: str
    african_genres: str
    amapiano: str
    reggae: str
    api: str
    hardware: str
    licence: str
    commercial_use: str
    quality: str
    notes: list = field(default_factory=list)


class Provider:
    name = "base"
    capabilities: Capabilities = None

    def submit(self, jobs: list[Job]) -> str:
        """Start generation. Returns a batch id."""
        raise NotImplementedError

    def poll(self, batch_id: str) -> str:
        """Return one of: running, complete, error."""
        raise NotImplementedError

    def fetch(self, batch_id: str, dest) -> dict:
        """Download outputs to dest; return manifest dict {'runtime_seconds':..., 'takes': [...]}."""
        raise NotImplementedError
