"""Check two suspicious 0000 prefixes using actual original-DOL references."""
import hashlib,json,struct
from inspect_discs import ROOT,save

def main():
    b=(ROOT/'work/roundtrip/jp/main.dol').read_bytes();inv=json.loads((ROOT/'metadata/disc_inventory_jp.json').read_text())
    assert hashlib.sha256(b).hexdigest()==inv['dol']['sha256']
    def offset(address):
        s=next(s for s in inv['dol']['sections'] if s['ram_address']<=address<s['ram_address']+s['size'])
        return address-s['ram_address']+s['file_offset']
    first=struct.unpack_from('>I',b,0x21317c)[0];assert first==0x80203560
    # Exact straight-line lis/addi pair. Intervening addi writes r29, not r3.
    at=offset(0x8008a314);w1,w2,w3=struct.unpack_from('>3I',b,at)
    assert w1>>26==15 and (w1>>21)&31==3 and (w1>>16)&31==0
    assert w2>>26==14 and (w2>>21)&31==29 and (w2>>16)&31==29
    assert w3>>26==14 and (w3>>21)&31==4 and (w3>>16)&31==3
    low=w3&65535;low=low-65536 if low&32768 else low
    second=(((w1&65535)<<16)+low)&0xffffffff;assert second==0x80209ec8
    rows=[]
    for old,address,evidence in [(0x20055c,first,dict(kind='data_pointer',file_offset=0x21317c)),
        (0x206ec4,second,dict(kind='straight_line_instruction_pair',ram_addresses=[0x8008a314,0x8008a31c],raw_hex=b[at:at+12].hex()))]:
        off=offset(address);assert off==old+4 and b[old:off]==b'0000'
        end=b.index(0,off);text=b[off:end].decode('cp932')
        rows.append(dict(catalog_id=f'main.dol@{old:08x}',candidate_offset=old,referenced_text_offset=off,ram_address=address,
            prefix_hex=b[old:off].hex(),referenced_text=text,evidence=evidence))
    save(ROOT/'metadata/dol_string_boundary_evidence.json',dict(dol_sha256=inv['dol']['sha256'],records=rows,
        conclusion='References point four bytes past the 0000 prefix. Catalog migration deferred to preserve reviewed IDs and source snapshot; do not translate the prefix.',
        limits='String reference does not establish display call behavior or cover all DOL strings.',catalog_changed=False,new_iso_built=False))
    print('Two DOL string starts corroborated; catalog and ISO unchanged.')

if __name__=='__main__':main()
