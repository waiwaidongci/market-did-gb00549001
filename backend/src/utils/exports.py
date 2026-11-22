import csv
from src.config.settings import ARTIFACTS


def safe_cell(value):
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@'))
                                   or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def write_report(run_id, attempt, result):
    """把完整结果写成 CSV；置换计数未完成时不提供配对、实测差分和计数。"""

    permutation = result.get('permutation') or {}
    if not permutation.get('complete'):
        raise ValueError('置换计数尚未完成，稍后重试后可下载完整结果。')
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    name = f'analysis-{run_id}-{attempt}.csv'
    path = ARTIFACTS / name
    staging = path.with_suffix('.tmp')
    with staging.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([safe_cell(result['headline'])])
        writer.writerow([safe_cell(result.get('note', ''))])
        for metric in result['metrics']:
            writer.writerow([safe_cell(metric['label']), safe_cell(metric['value']), safe_cell(metric.get('detail', ''))])
        writer.writerow([])
        writer.writerow([safe_cell('配对置换计数')])
        writer.writerow(['实测等权双重差分（分钟）', safe_cell(permutation['observed'])])
        writer.writerow(['绝对值不小于实测值的分配数', safe_cell(permutation['count'])])
        writer.writerow(['分配总数', safe_cell(permutation['total'])])
        writer.writerow(['置换比例', safe_cell(permutation['ratio'])])
        writer.writerow([])
        writer.writerow([safe_cell('参与置换的配对')])
        writer.writerow([safe_cell('配对'), safe_cell('试点市场'), safe_cell('对照市场'), safe_cell('配对双重差分（分钟）')])
        writer.writerows([safe_cell(item['pair']), safe_cell(item['treated']), safe_cell(item['control']),
                          safe_cell(item['effect'])] for item in permutation['pairs'])
        excluded = permutation.get('excluded') or []
        if excluded:
            writer.writerow([])
            writer.writerow([safe_cell('整对剔除说明')])
            writer.writerow([safe_cell('配对'), safe_cell('说明')])
            writer.writerows([safe_cell(item['pair']), safe_cell(item['reason'])] for item in excluded)
        for table in result['tables']:
            writer.writerow([])
            writer.writerow([safe_cell(table['title'])])
            columns = table['columns']
            writer.writerow([safe_cell(column['label']) for column in columns])
            writer.writerows([safe_cell(row.get(column['key'])) for column in columns] for row in table['rows'])
    staging.replace(path)
    return name
