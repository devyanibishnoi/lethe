import random
from datetime import datetime, timedelta, timezone

from sentence_transformers import SentenceTransformer

TENANT_IDS = [
    "00000000-0000-0000-0000-000000000001",
    "00000000-0000-0000-0000-000000000002",
]

FIRST_NAMES = [
    "amara", "devon", "priya", "kenji", "leah",
    "mateo", "sofia", "noah", "zara", "ivan",
]

HOST_PREFIXES = ["web", "db", "api", "vpn", "build", "auth", "cache", "batch"]

TEMPLATES = [
    "failed login alert: {attempts} failed login attempts for user {name} from ip {ip} on host {hostname} at {timestamp}",
    "suspicious outbound traffic: host {hostname} sent {volume} MB to external ip {ip} at {timestamp}, flagged for review",
    "flagged process: unrecognized process '{process}' spawned by user {name} on host {hostname} at {timestamp}",
    "unusual cloud-storage access: user {name} downloaded {file_count} files from a shared bucket at {timestamp}, source ip {ip}",
]

PROCESS_NAMES = ["svc_updater.exe", "sysdiag.sh", "netcrawl", "backup_agent", "remote_shell"]


def random_ip():
    return f"{random.randint(1, 254)}.{random.randint(0, 254)}.{random.randint(0, 254)}.{random.randint(1, 254)}"


def random_hostname():
    prefix = random.choice(HOST_PREFIXES)
    return f"{prefix}-{random.randint(1, 40):02d}"


def random_timestamp():
    now = datetime.now(timezone.utc)
    delta = timedelta(days=random.randint(0, 90), seconds=random.randint(0, 86400))
    return (now - delta).isoformat()


def fill_template(template):
    return template.format(
        name=random.choice(FIRST_NAMES),
        ip=random_ip(),
        hostname=random_hostname(),
        timestamp=random_timestamp(),
        attempts=random.randint(3, 20),
        volume=random.randint(50, 900),
        file_count=random.randint(5, 200),
        process=random.choice(PROCESS_NAMES),
    )


_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def generate_corpus(num_documents):
    model = get_model()

    texts = [fill_template(random.choice(TEMPLATES)) for _ in range(num_documents)]
    embeddings = model.encode(texts, normalize_embeddings=False)

    records = []
    for i, (text, embedding) in enumerate(zip(texts, embeddings)):
        tenant_id = TENANT_IDS[i % len(TENANT_IDS)]
        records.append(
            {
                "tenant_id": tenant_id,
                "content": text,
                "embedding": embedding.tolist(),
            }
        )

    return records
