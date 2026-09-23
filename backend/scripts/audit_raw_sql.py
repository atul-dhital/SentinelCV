#!/usr/bin/env python3
"""
Audit raw SQL text() queries for safety.

All raw SQL queries should have bounded result sets or aggregate operations.
This script identifies and categorizes remaining text() queries.
"""

import os
import re
import sys

def audit_sql_queries():
    """Find and audit all text() SQL queries in API files."""
    api_dir = os.path.join(os.path.dirname(__file__), '../api')

    sql_queries = {}

    for filename in os.listdir(api_dir):
        if not filename.endswith('.py'):
            continue

        filepath = os.path.join(api_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()
            lines = content.split('\n')

        # Find text() queries
        for i, line in enumerate(lines):
            if 'text(' in line:
                # Extract query context
                query_start = i
                query_end = i + 1

                # Find complete query
                while query_end < len(lines) and ')' not in lines[query_end]:
                    query_end += 1

                query = '\n'.join(lines[query_start:query_end+1])

                # Analyze safety
                is_safe = analyze_sql_safety(query)

                key = f"{filename}:{i+1}"
                sql_queries[key] = {
                    'query': query[:100] + '...',
                    'safe': is_safe,
                    'reason': get_safety_reason(query),
                }

    # Report
    print(f"\n{'='*60}")
    print(f"SQL Query Audit Report")
    print(f"{'='*60}\n")

    safe_count = sum(1 for q in sql_queries.values() if q['safe'])
    total_count = len(sql_queries)

    print(f"Total text() queries: {total_count}")
    print(f"Safe queries: {safe_count}/{total_count}")
    print(f"Safety rate: {100*safe_count/total_count:.0f}%\n")

    if total_count > 0:
        print("Query Details:\n")
        for key, query_info in sorted(sql_queries.items()):
            status = "[SAFE]" if query_info['safe'] else "[REVIEW]"
            print(f"{status} {key}")
            print(f"  Reason: {query_info['reason']}")

    return safe_count == total_count

def analyze_sql_safety(query):
    """Check if SQL query is safe (bounded result set)."""
    query_upper = query.upper()

    # Safe patterns
    safe_patterns = [
        'LIMIT',           # Explicit limit
        'COUNT(',          # Aggregation
        'MAX(',            # Aggregation
        'MIN(',            # Aggregation
        'SUM(',            # Aggregation
        'AVG(',            # Aggregation
        'GROUP BY',        # Grouped results
        'WHERE .* = ',     # Single row lookup
        'RETURNING',       # Limited result
    ]

    for pattern in safe_patterns:
        if pattern in query_upper:
            return True

    return False

def get_safety_reason(query):
    """Explain why query is/isn't safe."""
    query_upper = query.upper()

    if 'LIMIT' in query_upper:
        return "Has explicit LIMIT clause"
    elif 'COUNT(' in query_upper or 'SUM(' in query_upper:
        return "Aggregation query (returns single row)"
    elif 'GROUP BY' in query_upper:
        return "Grouped query (bounded groups)"
    elif 'WHERE' in query_upper and '=' in query_upper:
        return "Single row lookup (WHERE clause)"
    else:
        return "No obvious bounds - may need review"

if __name__ == '__main__':
    all_safe = audit_sql_queries()
    sys.exit(0 if all_safe else 1)
