import hashlib
import imagehash
from PIL import Image
import io


def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def compute_phash(pil_image: Image.Image) -> str:
    """Compute perceptual hash from a PIL Image. Returns hex string."""
    return str(imagehash.phash(pil_image))


def phash_similarity(hash1_hex: str, hash2_hex: str) -> float:
    """
    Compare two phash hex strings.
    Returns similarity as percentage (0.0 - 100.0).
    pHash produces a 64-bit hash, so max hamming distance = 64.
    """
    try:
        h1 = imagehash.hex_to_hash(hash1_hex)
        h2 = imagehash.hex_to_hash(hash2_hex)
        distance = h1 - h2  # hamming distance
        similarity = max(0.0, (64 - distance) / 64 * 100)
        return round(similarity, 2)
    except Exception:
        return 0.0

def compare_fields(stored_fields: dict, query_fields: dict) -> dict:
    """
    Compare AI-extracted fields between stored certificate and query document.
    Uses dynamic keys from stored_fields instead of hardcoded field names.
    Returns: {score: float 0-1, matches: dict, details: list}
    """
    # Use the actual keys from stored_fields (dynamic template fields)
    keys = list(stored_fields.keys())

    matches = {}
    match_count = 0
    total_comparable = 0
    details = []

    for key in keys:
        stored_val = (stored_fields.get(key) or '').strip().lower()
        query_val  = (query_fields.get(key) or '').strip().lower()

        if not stored_val and not query_val:
            continue  # both missing, skip

        total_comparable += 1

        if not stored_val or not query_val:
            details.append({
                'field': key,
                'stored': stored_fields.get(key),
                'query': query_fields.get(key),
                'match': False,
                'note': 'Missing in one'
            })
            matches[key] = False
            continue

        matched = stored_val == query_val or stored_val in query_val or query_val in stored_val
        if matched:
            match_count += 1
        matches[key] = matched
        details.append({
            'field': key,
            'stored': stored_fields.get(key),
            'query': query_fields.get(key),
            'match': matched
        })

    score = match_count / total_comparable if total_comparable > 0 else 0.0
    return {
        'score': round(score, 3),
        'matches': matches,
        'details': details,
        'match_count': match_count,
        'total': total_comparable
    }

def determine_status(sha256_match: bool, phash_score, field_comparison: dict):
    """
    Determine overall validation status.
    Returns: (status_code, confidence, description)
    """
    field_score = field_comparison.get('score', 0)

    if sha256_match:
        return 'AUTHENTIC', 100.0, 'Exact file match — SHA-256 verified'

    if phash_score is None:
        # DOCX or no visual hash
        if field_score >= 0.75:
            conf = round(field_score * 90, 1)
            return 'LIKELY_AUTHENTIC', conf, 'Fields match strongly (no visual hash available)'
        elif field_score >= 0.5:
            conf = round(field_score * 70, 1)
            return 'REVIEW_NEEDED', conf, 'Partial field match — manual review recommended'
        else:
            return 'NOT_FOUND', 0.0, 'No matching certificate found in the system'

    # Weighted confidence: phash 60%, fields 40%
    conf = round(phash_score * 0.6 + field_score * 100 * 0.4, 1)

    if phash_score >= 90 and field_score >= 0.75:
        return 'AUTHENTIC', conf, 'High visual similarity and field match'
    elif phash_score >= 90 and field_score >= 0.5:
        return 'LIKELY_AUTHENTIC', conf, 'High visual similarity with partial field match'
    elif phash_score >= 90 and field_score < 0.5:
        return 'SUSPICIOUS', conf, 'High visual similarity but fields do not match — possible tampering'
    elif phash_score >= 70:
        return 'REVIEW_NEEDED', conf, 'Moderate visual similarity — manual review recommended'
    elif phash_score >= 50:
        return 'UNLIKELY', conf, 'Low visual similarity — likely not authentic'
    else:
        return 'NOT_FOUND', conf, 'No matching certificate found in the system'
