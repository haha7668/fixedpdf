"""Opt-in real service check; creates full-page PDF/PNG and auditable reports."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pdf_translation as translation
import server


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--book', required=True)
    parser.add_argument('--pages', type=int, nargs='+', required=True)
    parser.add_argument('--allow-service', action='store_true', required=True)
    parser.add_argument('--reuse', action='store_true', help='Reuse checked translations with identical source text')
    parser.add_argument('--trace', action='store_true', help='Save local response diagnostics (contains document text)')
    args = parser.parse_args()
    runtime = Path(os.environ['LOCALAPPDATA']) / 'pdf_reader'
    server.AI_CONFIG_PATH = str(runtime / 'ai_config.json')
    server._load_ai_config()
    source = runtime / 'books' / args.book / 'book.pdf'
    output = Path('output/pdf') / args.book
    output.mkdir(parents=True, exist_ok=True)
    for number in args.pages:
        plan = translation.analyze_page(str(source), number)
        targets = {}
        previous = output / f'page-{number}.pending.json'
        if not previous.exists():
            previous = output / f'page-{number}.json'
        if args.reuse and previous.exists():
            data = json.loads(previous.read_text(encoding='utf-8'))
            known = {r['source']: data['targets'].get(r['id']) for r in data['plan']['regions']}
            for region in plan['regions']:
                target = known.get(region['source'])
                if target and translation.Counter(translation.NUMBERS.findall(target)) == translation.Counter(
                        translation.NUMBERS.findall(region['source'])):
                    targets[region['id']] = target
        remaining = {**plan, 'regions': [r for r in plan['regions'] if r['id'] not in targets]}
        responses = []
        async def complete(prompt, **kwargs):
            response, provider = await server._ai_complete(prompt, **kwargs)
            responses.append({'request': json.loads(prompt.split('\n', 1)[1]), 'response': response,
                              'provider': provider})
            return response, provider
        new_targets, warnings = await translation.translate_regions(remaining, complete)
        if args.trace:
            (output / f'page-{number}.responses.json').write_text(
                json.dumps(responses, ensure_ascii=False, indent=2), encoding='utf-8')
        targets.update(new_targets)
        plan['warnings'].extend(warnings)
        destination = output / f'page-{number}-zh-CN.pdf'
        (output / f'page-{number}.pending.json').write_text(
            json.dumps({'plan': plan, 'targets': targets}, ensure_ascii=False, indent=2), encoding='utf-8')
        report = translation.render_page(str(source), plan, targets, str(destination))
        (output / f'page-{number}.json').write_text(
            json.dumps({'report': report, 'plan': plan, 'targets': targets}, ensure_ascii=False, indent=2),
            encoding='utf-8')
        with translation.fitz.open(destination) as doc:
            doc[0].get_pixmap(matrix=translation.fitz.Matrix(1.7, 1.7)).save(str(destination.with_suffix('.png')))
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
