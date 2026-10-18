"""Demo compiler and explicitly selected real integration adapters."""

from app.demo import demo_rules
from app.models import CompileResult
from store.config import Configuration, validate_configuration


def demo_compile(prompt, zones):
    text = prompt.lower()
    result = CompileResult(warnings=['DEMO compiler: fixed demo-policy mapping; no LLM used.'])
    if any(word in text for word in ['concealed', 'identity', 'facial', 'age', 'intent']):
        result.unsupported.append('This condition is not reliably observable with the supported camera checks.')
        return result
    wants = ['clear' in text and 'bag' in text,
             ('professional' in text or 'pro camera' in text) and 'camera' in text,
             'exit' in text and any(word in text for word in ['clear', 'block', 'bag', 'chair'])]
    for wanted, rule in zip(wants, demo_rules()):
        if not wanted:
            continue
        matches = [zone for zone in zones if zone.id == rule.zone or
                   zone.name.lower().replace('-', ' ') == rule.zone.replace('_', ' ')]
        if len(matches) != 1:
            result.warnings.append(f'Assign a unique zone for {rule.name} before compiling.')
            continue
        result.rules.append(rule.model_copy(update={'zone': matches[0].id}))
    if not result.rules:
        result.warnings.append('Demo mode supports only the documented entrance and exit examples.')
    return result


def integrated_compile(prompt, zones):
    from policy.compiler import compile_policy
    raw = compile_policy(prompt, zones)
    return CompileResult.model_validate(raw.model_dump() if hasattr(raw, 'model_dump') else raw)


def validate_compile_result(result, cameras, zones):
    result = CompileResult.model_validate(result.model_dump() if hasattr(result, 'model_dump') else result)
    validate_configuration(Configuration(cameras=cameras, zones=zones, rules=result.rules))
    return result
