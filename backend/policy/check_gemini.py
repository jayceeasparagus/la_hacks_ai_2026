"""python -m policy.check_gemini: does our Gemini setup actually work?

Reads .env like the server does, says which mode is configured (Gemini API key, Vertex AI express
key, or Vertex AI with gcloud credentials), then makes one real structured compile call and one real
image verification, and explains any failure in plain words. Never prints the key itself.
"""

import os
import sys
import time

import numpy as np
from dotenv import load_dotenv

from policy import llm


def _flag(name: str) -> bool:
    return os.getenv(name, '').strip().lower() in ('1', 'true', 'yes')


def describe_mode() -> tuple[str, list[str]]:
    key_name = next((n for n in ('GOOGLE_API_KEY', 'GEMINI_API_KEY') if os.getenv(n)), None)
    key = os.getenv(key_name) if key_name else ''
    notes = [f'{key_name}: {len(key)} characters, starts {key[:4]!r}' if key_name else 'no API key set']
    if _flag('GOOGLE_GENAI_USE_VERTEXAI'):
        project, location = os.getenv('GOOGLE_CLOUD_PROJECT'), os.getenv('GOOGLE_CLOUD_LOCATION')
        notes.append(f'GOOGLE_CLOUD_PROJECT={project or "(unset)"}  GOOGLE_CLOUD_LOCATION={location or "(unset)"}')
        if key_name:
            return 'Vertex AI (express mode, API key)', notes
        return 'Vertex AI (gcloud application-default credentials)', notes
    if key_name:
        return 'Gemini Developer API (API key)', notes
    return 'none', notes


def explain(error: Exception) -> str:
    text = str(error)
    low = text.lower()
    if 'gemini_api_key is not set' in low or 'no api key' in low:
        return ('No key found. Copy .env.example to .env at the repo root and set GEMINI_API_KEY '
                '(AI Studio key) or, for Vertex AI, GOOGLE_GENAI_USE_VERTEXAI=true plus GOOGLE_API_KEY.')
    if 'api_key_service_blocked' in low:
        api = 'Vertex AI API' if 'aiplatform' in low else 'Generative Language API'
        return (f'This key\'s API restrictions block the {api}. In Google Cloud console > APIs & Services > '
                f'Credentials > this key > API restrictions, add "{api}" (or choose "Don\'t restrict key"), make sure '
                'that API is enabled for the project, wait a few minutes, and run this check again.')
    if 'prepayment credits are depleted' in low or 'error code: 402' in low:
        return ('The key works, but this project\'s prepaid Gemini API credits are used up. Add credits at '
                'https://ai.studio/projects (Billing), or use a key from a project on the free tier, or switch to '
                'Vertex AI (allow "Vertex AI API" on an express key) so usage bills to Google Cloud credits.')
    if 'api keys are not supported by this api' in low or 'credentials_missing' in low:
        return ('Vertex AI refused the key: it is not a Vertex AI express-mode key. Use it in Gemini API mode '
                '(remove GOOGLE_GENAI_USE_VERTEXAI), create an express key in Vertex AI Studio, or use '
                'gcloud auth application-default login with GOOGLE_CLOUD_PROJECT.')
    if 'api key not valid' in low or 'api_key_invalid' in low:
        return ('The key was rejected. Check it was copied fully. A Vertex AI key needs '
                'GOOGLE_GENAI_USE_VERTEXAI=true; an AI Studio key must not have it set.')
    if 'has not been used' in low or 'is disabled' in low or 'service_disabled' in low:
        return ('The API is not enabled for this key\'s Google Cloud project: enable "Generative Language API" '
                '(Gemini API) or "Vertex AI API" (Vertex mode) in the Cloud console, then wait a minute.')
    if 'permission_denied' in low or '403' in low:
        return ('Permission denied: the key is restricted to other APIs, or the project lacks access. In the Cloud '
                'console, allow this API in the key\'s "API restrictions".')
    if 'billing' in low:
        return 'The Google Cloud project needs billing enabled (Vertex AI credits count once billing is set up).'
    if '429' in low or 'resource_exhausted' in low or 'quota' in low:
        return 'Quota exceeded: wait a minute, or lower the verifier rate in verify/ratelimit.py for the free tier.'
    if 'not found' in low or '404' in low:
        return (f'Not found: the model {llm.policy_model()!r} or this API path is unavailable in this mode. '
                'Try GEMINI_MODEL=gemini-2.5-flash, and in Vertex mode set GOOGLE_CLOUD_LOCATION=us-central1.')
    if 'could not automatically determine credentials' in low or 'default credentials' in low:
        return 'Vertex AI without a key needs: gcloud auth application-default login, plus GOOGLE_CLOUD_PROJECT.'
    if isinstance(error, TimeoutError) or 'timed out' in low:
        return 'Timed out: check the network connection, then try again.'
    return f'Unexpected error: {text[:300]}'


def main() -> int:
    load_dotenv()
    if _flag('POLICYLENS_FAKE_LLM'):
        print('Note: POLICYLENS_FAKE_LLM is on (offline mode); ignoring it for this check.')
        os.environ['POLICYLENS_FAKE_LLM'] = '0'
    mode, notes = describe_mode()
    print(f'Mode: {mode}')
    for note in notes:
        print(f'  {note}')
    print(f'  models: compile={llm.policy_model()}  verify={llm.verify_model()}')

    ok = True
    llm.reset_breaker()
    started = time.monotonic()
    try:
        text = llm.call_structured('Reply with the word ok.',
                                   {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']},
                                   model=llm.policy_model(), timeout=20)
        print(f'1. Structured compile call: OK in {(time.monotonic() - started) * 1000:.0f} ms -> {text[:60]}')
    except Exception as exc:
        ok = False
        print(f'1. Structured compile call: FAILED after {(time.monotonic() - started) * 1000:.0f} ms')
        print(f'   {explain(exc)}')

    from verify.verifier import verify_crop

    llm.reset_breaker()
    image = np.full((240, 240, 3), 235, np.uint8)
    image[60:200, 70:170] = (40, 50, 120)  # a solid dark "bag"
    started = time.monotonic()
    verdict = verify_crop(image, 'transparent_bag')
    took = (time.monotonic() - started) * 1000
    if verdict.reason in ('verification unavailable', 'verification timed out', 'verification busy'):
        ok = False
        print(f'2. Image verification: FAILED ({verdict.reason}) after {took:.0f} ms; see the error above or the log.')
    else:
        print(f'2. Image verification: OK in {took:.0f} ms -> answer={verdict.answer} confidence={verdict.confidence:.2f} '
              f'reason={verdict.reason!r}')
    print('Gemini is working.' if ok else 'Gemini is NOT working yet.')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
