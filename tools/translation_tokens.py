"""Unicode translation segments plus unchanged source controls; no ROM encoding."""
import re

MARKER=re.compile(r'<(\d+)>')

def bounds(row):
    indices=[i for i,t in enumerate(row['tokens']) if t['kind'] in ('text','format','icon')]
    if not indices:raise ValueError('No displayed content: '+row['id'])
    return min(indices),max(indices)

def template(row):
    lo,hi=bounds(row)
    return ''.join(t['source'] if t['kind']=='text' else '\n' if t['kind']=='newline' else f'<{i}>'
        for i,t in enumerate(row['tokens']) if lo<=i<=hi)

def translated_tokens(row):
    """Preserve every control in order, including controls outside visible text."""
    lo,hi=bounds(row);source=row['tokens'];target=row['translation']
    if not isinstance(target,str):raise ValueError('No translation')
    # DOL C strings have literal LF/tab bytes inside their sole text token.
    # Script newlines remain indexed control tokens handled below.
    if row['kind']=='dol_rodata_string_candidate':
        if lo!=hi or source[lo]['kind']!='text':raise ValueError('Unexpected DOL token structure: '+row['id'])
        if MARKER.search(target):raise ValueError('Unexpected DOL marker: '+row['id'])
        if re.findall(r'[\n\t]',source[lo]['source'])!=re.findall(r'[\n\t]',target):
            raise ValueError('Changed DOL literal controls: '+row['id'])
        return list(source[:lo])+[dict(kind='text',source=target)]+list(source[hi+1:])
    expected=[i for i in range(lo,hi+1) if source[i]['kind'] not in ('text','newline')]
    actual=[int(m.group(1)) for m in MARKER.finditer(target)]
    if actual!=expected:raise ValueError('Missing/reordered control markers: '+row['id'])
    if target.count('\n')!=sum(t['kind']=='newline' for t in source[lo:hi+1]):raise ValueError('Changed line count: '+row['id'])
    # Newlines are controls too. Check their ordering against every named marker.
    old_order=[i for i in range(lo,hi+1) if source[i]['kind']!='text']
    newlines=iter(i for i in range(lo,hi+1) if source[i]['kind']=='newline')
    output=list(source[:lo]);order=[];cursor=0
    for m in re.finditer(r'<(\d+)>|\n',target):
        if m.start()>cursor:output.append(dict(kind='text',source=target[cursor:m.start()]))
        i=int(m.group(1)) if m.group(1) else next(newlines);order.append(i);output.append(dict(source[i]));cursor=m.end()
    if target[cursor:]:output.append(dict(kind='text',source=target[cursor:]))
    if order!=old_order:raise ValueError('Control crossed line boundary: '+row['id'])
    output.extend(source[hi+1:])
    assert [(t['kind'],t['hex']) for t in output if t['kind']!='text']==[(t['kind'],t['hex']) for t in source if t['kind']!='text']
    return output
