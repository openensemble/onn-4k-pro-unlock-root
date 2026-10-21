"""Report one secure unlock request without claiming cold-boot persistence."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,struct
BASE=Path(__file__).resolve().parent
OUT=0x1040
ALLOWED=set(range(OUT,OUT+0xb8))|set(range(OUT+0xc0,OUT+0xd0))|set(range(OUT+0xf0,OUT+0xf8))|set(range(OUT+0x100,OUT+0x160))|set(range(OUT+0x180,OUT+0x2a0))

def collect_local(session):
    plan=json.loads((BASE/'experiment-plan.json').read_text());original=(BASE/plan['payload_file']).read_bytes()
    result={'time_utc':datetime.now(timezone.utc).isoformat(),'secure_state_change_observed':False,'unlock_request_accepted':False,
            'root_proven':False,'permanent_unlock_proven':False,'cold_boot_persistence_tested':False,
            'captures':{name:(session/name).exists() for name in plan['new_usb_files']}}
    before=session/'ONNBEG24.BIN';result['pre_entry_checkpoint_matches_input']=before.exists() and before.read_bytes()==original
    for name,key in [('ONNST24.TXT','early_markers'),('ONNCAP24.TXT','markers')]:
        path=session/name;env={}
        if path.exists():env=dict(line.split('=',1) for line in path.read_bytes().rstrip(b'\0').decode(errors='replace').splitlines() if '=' in line)
        result[key]={k:v for k,v in env.items() if k.startswith('onn24_')}
    path=session/'ONNRET24.BIN'
    if path.exists():
        data=path.read_bytes();result['returned_bytes']=len(data);result['returned_sha256']=hashlib.sha256(data).hexdigest()
        if len(data)==len(original)==0x1440:
            result['only_expected_bytes_changed']={i for i,(a,b) in enumerate(zip(original,data)) if a!=b}<=ALLOWED
            result['probe_code_unchanged']=data[64:OUT]==original[64:OUT]
            result['marker']=data[OUT:OUT+4].decode(errors='replace');result['status']=struct.unpack_from('<I',data,OUT+4)[0]
            context=dict(zip(['x18','lr','sp','current_el','sctlr_el2','daif','relocaddr','getter','primary_reader','tee_reader','original_par'],struct.unpack_from('<11Q',data,OUT+8)))
            result['context']={k:hex(v) for k,v in context.items()}
            fields={'before_read_success':0x60,'before_state':0x64,'getter_calls':0x68,'write_requests':0x6c,
                    'open_success':0x80,'open_ta_result':0x84,'open_origin':0x88,'session_id':0x8c,
                    'invoke_transport_result':0x90,'invoke_ta_result':0x94,'invoke_origin':0x98,'close_result':0x9c,
                    'after_read_success':0xa0,'after_state':0xa4,'all_prefixes_match_after':0xa8,'open_calls':0xac}
            result['calls']={k:struct.unpack_from('<I',data,OUT+offset)[0] for k,offset in fields.items()}
            calls=result['calls'];result['request_argument']=list(struct.unpack_from('<4I',data,OUT+0x100));result['parameter']=list(struct.unpack_from('<4Q',data,OUT+0x110))
            result['prefixes']={}
            for index,address in enumerate(plan['guard_addresses']):
                start=OUT+0x180+index*32;pre=data[start:start+16].hex();post=data[start+16:start+32].hex()
                result['prefixes'][address]={'before':pre,'after':post,'matches_stock':pre==post==plan['prefixes'][address]}
            result['stock_prefixes_unchanged']=all(v['matches_stock'] for v in result['prefixes'].values())
            after_sp,after_x18=struct.unpack_from('<2Q',data,OUT+0x70);after_sctlr=struct.unpack_from('<Q',data,OUT+0xf0)[0]
            result['call_context_preserved']=(after_sp,after_x18,after_sctlr)==(context['sp'],context['x18'],context['sctlr_el2'])
            result['native_completion_proven']=bool(result['pre_entry_checkpoint_matches_input'] and result['only_expected_bytes_changed'] and result['probe_code_unchanged']
                and result['marker']=='ON24' and context['current_el']==8 and context['x18']==0xb96055c0 and context['lr']==0xbf662828
                and context['sp']%16==0 and context['getter']==0xbf621d24 and result['markers'].get('onn24_go')=='returned_zero')
            full=bool(result['native_completion_proven'] and result['stock_prefixes_unchanged'] and result['call_context_preserved'])
            request_ok=bool(full and calls['write_requests']==1 and calls['open_calls']==1 and calls['open_success']==1 and calls['open_ta_result']==0
                and result['request_argument'][:2]==[3,calls['session_id']] and result['parameter']==[1,0,0,0])
            result['unlock_request_accepted']=bool(request_ok and calls['invoke_transport_result']==0 and calls['invoke_ta_result']==0)
            result['secure_state_change_observed']=bool(full and calls['getter_calls']==2 and calls['before_read_success']==calls['after_read_success']==1
                and calls['before_state']==1 and calls['after_state']==0 and request_ok)
    if result['secure_state_change_observed']:
        conclusion='The stock secure-state reader changed from locked (1) to unlocked (0) after one request. Cold-boot persistence and custom-image boot remain unproven.'
    elif result.get('native_completion_proven'):
        c=result['calls']
        if c['write_requests']==1:
            conclusion=f"One unlock request returned transport={c['invoke_transport_result']:#x}, trusted-service={c['invoke_ta_result']:#x}; after-read success={c['after_read_success']}, state={c['after_state']}. No permanent unlock proved."
        else:conclusion=f"Probe returned status {result['status']} without issuing a secure-state write."
    elif result['pre_entry_checkpoint_matches_input']:conclusion='Before-entry checkpoint exists, but native completion and write outcome are unproven. Do not repeat the request.'
    else:conclusion='No matching before-entry checkpoint; inspect setup captures before assessing whether execution occurred.'
    result['conclusion']=conclusion;(session/'capture-validation.json').write_text(json.dumps(result,indent=2)+'\n');return result
