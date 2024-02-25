import hashlib
import hmac


def github_verify_signature(github_app_secret: str, x_hub_signature: str,
                            data: bytes) -> bool:
    # Use HMAC to compute the hash
    hmac_gen = hmac.new(github_app_secret.encode(), data, hashlib.sha1)
    expected_signature = 'sha256=' + hmac_gen.hexdigest()
    return hmac.compare_digest(expected_signature, x_hub_signature)
