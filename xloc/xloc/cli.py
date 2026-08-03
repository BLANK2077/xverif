import argparse
import sys

from .resolver import cmd_resolve, cmd_context, resolve_payload, context_payload, render_payload
from .stats import cmd_stats, stats_payload, render_stats
from .annotate import cmd_annotate
from .xout import dumps


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='xloc',
        description='LLM-friendly UVM source-location mapper'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # resolve
    p_resolve = sub.add_parser('resolve', help='resolve a loc_id to a source file')
    p_resolve.add_argument('loc_id', help='loc_id to resolve (e.g. L_00000001)')
    p_resolve.add_argument('--map', dest='map_path',
                           required=True,
                           help='path to sidecar JSONL map file')
    p_resolve.add_argument('--json', action='store_true', help='emit JSON')

    # context
    p_ctx = sub.add_parser('context', help='resolve a loc_id and show context at an explicit line')
    p_ctx.add_argument('loc_id', help='loc_id to resolve')
    p_ctx.add_argument('--map', dest='map_path',
                        required=True,
                        help='path to sidecar JSONL map file')
    p_ctx.add_argument('--line', type=_positive_int, required=True,
                        help='positive source line number preserved in the log')
    p_ctx.add_argument('--before', type=_non_negative_int, default=20,
                        help='lines before target (default: 20)')
    p_ctx.add_argument('--after', type=_non_negative_int, default=20,
                        help='lines after target (default: 20)')
    p_ctx.add_argument('--json', action='store_true', help='emit JSON')

    # stats
    p_stats = sub.add_parser('stats', help='count loc_id frequency in a log')
    p_stats.add_argument('log', help='path to simulation log')
    p_stats.add_argument('--map', dest='map_path',
                          help='path to sidecar JSONL map file')
    p_stats.add_argument('--top', type=_positive_int, default=20,
                          help='show top N source locations (default: 20)')
    p_stats.add_argument('--json', action='store_true', help='emit JSON')

    # annotate
    p_ann = sub.add_parser('annotate', help='insert location hints into a log')
    p_ann.add_argument('log', help='path to simulation log')
    p_ann.add_argument('--map', dest='map_path',
                        help='path to sidecar JSONL map file')
    p_ann.add_argument('--format', choices=('xout', 'json', 'raw'),
                       default='xout',
                       help='output format (default: xout; raw emits the annotated log artifact)')

    args = parser.parse_args()

    if args.command == 'resolve':
        if args.json:
            payload = resolve_payload(args.loc_id, args.map_path)
            print(dumps(payload))
            sys.exit(0 if payload.get("ok") else 1)
        sys.exit(cmd_resolve(args.loc_id, args.map_path))
    elif args.command == 'context':
        if args.json:
            payload = context_payload(args.loc_id, args.map_path, args.line, args.before, args.after)
            print(dumps(payload))
            sys.exit(0 if payload.get("ok") else 1)
        sys.exit(cmd_context(args.loc_id, args.map_path, args.line, args.before, args.after))
    elif args.command == 'stats':
        if args.json:
            payload = stats_payload(args.log, args.map_path, args.top)
            print(dumps(payload))
            sys.exit(0 if payload.get("ok") else 1)
        sys.exit(cmd_stats(args.log, args.map_path, args.top))
    elif args.command == 'annotate':
        sys.exit(cmd_annotate(args.log, args.map_path, args.format))


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed
