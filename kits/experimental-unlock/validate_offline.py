"""Model conditional one-write behavior, exact TEE request, and failure handling."""
from pathlib import Path
import json,struct,sys,tempfile
BASE=Path(__file__).resolve().parent
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
import unicorn.arm64_const as r
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from collect_result import collect_local,ALLOWED,OUT
ENTRY,RETURN,GD,SP=0x3000040,0xbf662828,0xb96055c0,0xb96040f0
plan=json.loads((BASE/'experiment-plan.json').read_text());image=(BASE/plan['payload_file']).read_bytes()
fixture = json.loads((BASE / 'emulator-fixture.json').read_text())
binary = bytearray(fixture['allocation_size'])
for address, fragment in fixture['chunks'].items():
    offset = int(address, 16) - int(fixture['base'], 16)
    binary[offset:offset + len(bytes.fromhex(fragment))] = bytes.fromhex(fragment)
binary = bytes(binary)
instructions={}
for i in Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(image[64:OUT],ENTRY):
    instructions[i.address]=(i.mnemonic,i.op_str)
    assert i.mnemonic not in ('bl','stp','ldp','dc','ic','tlbi','smc')
    if i.mnemonic=='blr':assert i.op_str=='x4'
    if i.mnemonic=='ret':break
cases=[];captures={}
for name,change,status,writes in [
 ('accepted',{},2,1),('tee_rejected',{'tee_result':0xffff0001},8,1),
 ('transport_rejected',{'transport':0xffffffff},8,1),('success_without_change',{'keep_locked':True},10,1),
 ('error_with_state_change',{'transport':0xffffffff,'change_despite_error':True},12,1),
 ('readback_failed',{'after_rc':0},11,1),('readback_invalid',{'after_state':7},11,1),
 ('already_unlocked',{'initial_state':0},6,0),('initial_read_failed',{'before_rc':0},4,0),
 ('initial_state_invalid',{'initial_state':7},4,0),('open_transport_rejected',{'open_rc':0},7,0),
 ('open_ta_rejected',{'open_ta':0xffff0001},7,0),('wrong_el',{'currentel':4},3,0),
 ('wrong_gd',{'gd':GD+16},3,0),('unaligned_stack',{'sp':SP+8},3,0),
 ('reader_prefix_mismatch',{'bad_prefix':0xbf621d24},9,0),('writer_prefix_mismatch',{'bad_prefix':0xbf621918},9,0),
 ('ta_uuid_mismatch',{'bad_prefix':0xbf70def8},9,0),('post_code_mismatch',{'post_change':True},5,1)
]:
    v={'currentel':8,'sctlr_el2':0x30c51835,'daif':0x2c0,'gd':GD,'sp':SP,'initial_state':1,'before_rc':1,'after_rc':1,
       'open_rc':1,'open_ta':0,'transport':0,'tee_result':0,**change}
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x3000000,0x2000);u.mem_write(0x3000000,image)
    u.mem_map(0xbf616000,0x1d0000);u.mem_write(0xbf616000,binary)
    u.mem_map(0xb9600000,0x6000);u.mem_write(GD+0x70,struct.pack('<Q',0xbf616000))
    if v.get('bad_prefix'):u.mem_write(v['bad_prefix'],b'XXXX')
    preserved={getattr(r,f'UC_ARM64_REG_X{n}'):0xabc00000+n*256 for n in range(18,30)};preserved[r.UC_ARM64_REG_X18]=v['gd']
    for reg,value in preserved.items():u.reg_write(reg,value)
    u.reg_write(r.UC_ARM64_REG_SP,v['sp']);u.reg_write(r.UC_ARM64_REG_X30,RETURN)
    state={'reads':0,'opens':0,'writes':0,'closes':0,'lock':v['initial_state'],'par':0x1122334400}
    def ret(value):
        pc=u.reg_read(r.UC_ARM64_REG_X30)
        for n in range(1,18):u.reg_write(getattr(r,f'UC_ARM64_REG_X{n}'),0xdead0000+n)
        u.reg_write(r.UC_ARM64_REG_X0,value);u.reg_write(r.UC_ARM64_REG_PC,pc)
    def on_code(u,address,size,_):
        if address==0xbf621d24:
            state['reads']+=1;first=state['reads']==1;rc=v['before_rc'] if first else v['after_rc']
            assert u.reg_read(r.UC_ARM64_REG_X0)==0x3000000+OUT+(0x64 if first else 0xa4)
            if rc:u.mem_write(u.reg_read(r.UC_ARM64_REG_X0),struct.pack('<I',state['lock'] if first else v.get('after_state',state['lock'])))
            if not first and v.get('post_change'):u.mem_write(0xbf621d24,b'XXXX')
            ret(rc);return
        if address==0xbf6217e0:
            state['opens']+=1;u.mem_write(0xbf7b7068,struct.pack('<Q',0xb9609000));u.mem_write(0xbf7b7070,bytes(0x30))
            u.mem_write(0xbf7b7094,struct.pack('<3I',42,v['open_ta'],4));ret(v['open_rc']);return
        if address==0xbf6c3598:
            state['writes']+=1
            assert state['reads']==1 and state['lock']==1 and state['opens']==1 and state['writes']==1
            assert u.reg_read(r.UC_ARM64_REG_X0)==0xb9609000 and u.reg_read(r.UC_ARM64_REG_X2)==1
            arg=u.reg_read(r.UC_ARM64_REG_X1);param=u.reg_read(r.UC_ARM64_REG_X3)
            assert arg==0x3000000+OUT+0x100 and param==0x3000000+OUT+0x110
            assert struct.unpack('<4I',bytes(u.mem_read(arg,16)))==(3,42,0,0)
            assert struct.unpack('<4Q',bytes(u.mem_read(param,32)))==(1,0,0,0)
            if (not v['transport'] and not v['tee_result'] and not v.get('keep_locked')) or v.get('change_despite_error'):state['lock']=0
            u.mem_write(arg+8,struct.pack('<2I',v['tee_result'],4));ret(v['transport']);return
        if address==0xbf6c3588:
            state['closes']+=1
            assert u.reg_read(r.UC_ARM64_REG_X0)==0xb9609000 and u.reg_read(r.UC_ARM64_REG_X1)==42
            ret(0);return
        mnemonic,operands=instructions[address]
        if mnemonic=='mrs':
            dst,src=operands.split(', ');value=state['par'] if src=='par_el1' else v[src]
            u.reg_write(getattr(r,'UC_ARM64_REG_'+dst.upper()),value);u.reg_write(r.UC_ARM64_REG_PC,address+4)
        elif mnemonic=='msr':
            assert operands=='par_el1, x3';state['par']=u.reg_read(r.UC_ARM64_REG_X3);u.reg_write(r.UC_ARM64_REG_PC,address+4)
    def on_write(u,access,address,size,value,_):
        assert set(range(address-0x3000000,address-0x3000000+size))<=ALLOWED,(name,hex(address),size)
    u.hook_add(UC_HOOK_CODE,on_code);u.hook_add(UC_HOOK_MEM_WRITE,on_write);u.emu_start(ENTRY,RETURN,count=2500)
    data=bytes(u.mem_read(0x3000000,len(image)))
    assert u.reg_read(r.UC_ARM64_REG_PC)==RETURN and u.reg_read(r.UC_ARM64_REG_X0)==0 and u.reg_read(r.UC_ARM64_REG_SP)==v['sp']
    assert all(u.reg_read(reg)==value for reg,value in preserved.items()) and state['par']==0x1122334400
    assert data[OUT:OUT+4]==b'ON24' and struct.unpack_from('<I',data,OUT+4)[0]==status,name
    assert state['writes']==writes and state['closes']==writes and state['opens']<=1 and state['reads']<=2
    assert struct.unpack_from('<I',data,OUT+0x6c)[0]==writes
    captures[name]=data;cases.append({'case':name,'passed':True,'status':status,'writes':writes,'reads':state['reads'],'abi_preserved':True})

collector=[]
for name,variant,mutation,changed,accepted in [
 ('accepted','accepted',None,True,True),('tee_rejected','tee_rejected',None,False,False),
 ('accepted_but_locked','success_without_change',None,False,True),('ambiguous_change','error_with_state_change',None,True,False),
 ('no_write','already_unlocked',None,False,False),('missing_checkpoint','accepted','missing',False,False),
 ('modified_code','accepted','code',False,False),('wrong_command','accepted','command',False,False),
 ('wrong_value','accepted','value',False,False),('wrong_readback','accepted','readback',False,True)
]:
    with tempfile.TemporaryDirectory() as directory:
        session=Path(directory);data=bytearray(captures[variant])
        if mutation=='code':data[64]^=1
        if mutation=='command':struct.pack_into('<I',data,OUT+0x100,1)
        if mutation=='value':struct.pack_into('<Q',data,OUT+0x118,1)
        if mutation=='readback':struct.pack_into('<I',data,OUT+0xa4,1)
        if mutation!='missing':(session/'ONNBEG24.BIN').write_bytes(image)
        (session/'ONNRET24.BIN').write_bytes(data);(session/'ONNCAP24.TXT').write_text('onn24_go=returned_zero\n')
        result=collect_local(session)
        assert result['secure_state_change_observed']==changed and result['unlock_request_accepted']==accepted,(name,result)
        assert result['permanent_unlock_proven'] is False
        collector.append({'case':name,'passed':True})
(BASE/'offline-validation.json').write_text(json.dumps({'native_cases':cases,'collector_cases':collector,'hardware_tested':False,
 'limits':'TEE operations and stock functions are modeled with caller-saved register clobbering. These tests prove request construction and control flow, not vendor acceptance or side effects.'},indent=2)+'\n')
print(json.dumps({'native_cases_passed':len(cases),'collector_cases_passed':len(collector),'device_contacted':False}))
