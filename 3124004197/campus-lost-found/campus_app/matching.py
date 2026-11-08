import math
import re
from datetime import date


def tokens(text):
    words = set(re.findall(r'[a-z0-9]+', text.lower()))
    chinese = ''.join(re.findall(r'[\u4e00-\u9fff]', text))
    words.update(chinese[i:i+2] for i in range(max(0, len(chinese)-1)))
    return words


def overlap(a, b):
    aa, bb = tokens(a), tokens(b)
    return len(aa & bb) / max(1, min(len(aa), len(bb)))


def score_candidates(target, candidates):
    results = []
    for item in candidates:
        reasons = []
        score = 5
        if target['category'] == item['category']:
            score += 30
            reasons.append('物品类别相同')
        similarity = overlap(target['title'] + target['description'], item['title'] + item['description'])
        score += similarity * 40
        if similarity > .1:
            reasons.append('公开描述存在相近特征')
        if overlap(target['location'], item['location']) > .2:
            score += 15
            reasons.append('登记地点接近或相同')
        days = abs((date.fromisoformat(target['occurred_on']) - date.fromisoformat(item['occurred_on'])).days)
        if days <= 3:
            score += 10
            reasons.append('登记日期相差不超过三天')
        results.append({'item': item, 'score': min(95, round(score)), 'reasons': reasons or ['可人工核对公开信息'],
                        'questions': ['核对未公开的物品特征、具体时间和地点。']})
    return sorted(results, key=lambda x: (-x['score'], -x['item']['id']))


def validate_ai_matches(raw, allowed):
    if not isinstance(raw, dict) or not isinstance(raw.get('matches'), list):
        raise ValueError('匹配格式错误')
    by_id = {item['id']: item for item in allowed}
    results, seen = [], set()
    for entry in raw['matches']:
        if not isinstance(entry, dict):
            continue
        ident = entry.get('id')
        if type(ident) is not int or ident not in by_id or ident in seen:
            continue
        score = entry.get('score')
        if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score):
            continue
        def strings(key):
            value = entry.get(key, [])
            return [s[:180] for s in value[:4] if isinstance(s, str) and s.strip()] if isinstance(value, list) else []
        results.append({'item': by_id[ident], 'score': round(max(0, min(100, score))),
                        'reasons': strings('reasons'), 'questions': strings('questions')})
        seen.add(ident)
    if raw['matches'] and not results:
        raise ValueError('无有效候选')
    return sorted(results, key=lambda x: -x['score'])[:8]
