"""Redact local paths in delivery copies while preserving URLs and dictionary keys.

Source files are never changed. Distinct absolute-path keys receive distinct tags,
so multi-actor input hashes cannot collapse into one dictionary entry.
"""
import hashlib
import re


PRIVATE_PATH = re.compile(
    r"(?<![A-Za-z0-9+._-])[A-Za-z]:[\\/](?!/)"
    r"|(?<![A-Za-z0-9._-])/(?:home|Users)/[^/]+/"
)
CREDENTIAL = re.compile(
    rb"(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    rb"|sk-proj-[A-Za-z0-9_-]{30,}"
    rb"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def has_private_path(value):
    # Public source URLs can legitimately contain /home/ or /Users/ components.
    if value.startswith(("https://", "http://")):
        return False
    return bool(PRIVATE_PATH.search(value))


def private_path_key(value):
    """Keep the basename and an irreversible path tag for each local-path key."""
    basename = re.split(r"[\\/]", value)[-1]
    tag = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"<local-file:{basename}:{tag}>"


def sanitize(value, *, replacement="<local artifact; original hash recorded>"):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            public_key = private_path_key(key) if isinstance(key, str) and has_private_path(key) else key
            if public_key in result:
                raise ValueError("Redacted dictionary key collision")
            result[public_key] = sanitize(item, replacement=replacement)
        return result
    if isinstance(value, list):
        return [sanitize(item, replacement=replacement) for item in value]
    if isinstance(value, str) and has_private_path(value):
        return replacement
    return value


def private_path_fields(value, location=""):
    """Report field locations, never secret values, including path-bearing keys."""
    result = []
    if isinstance(value, dict):
        for index, (key, item) in enumerate(value.items()):
            if isinstance(key, str) and has_private_path(key):
                result.append(f"{location}/<dictionary-key-{index}>")
            public_key = key if not isinstance(key, str) or not has_private_path(key) else f"<private-key-{index}>"
            result.extend(private_path_fields(item, f"{location}/{public_key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(private_path_fields(item, f"{location}/{index}"))
    elif isinstance(value, str) and has_private_path(value):
        result.append(location)
    return result
