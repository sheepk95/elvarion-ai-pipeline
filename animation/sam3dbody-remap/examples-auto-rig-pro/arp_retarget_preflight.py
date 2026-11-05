"""ARP mapping/range preflight; reads a loaded working copy or an explicit snapshot.

Example code for the remap_to_arp.py example (needs Blender and the paid Auto-Rig Pro add-on).
"""
import argparse,hashlib,json,math,sys
from pathlib import Path

def curves_for_slot(action,slot):
    # the F-curves of one action slot (layered actions, Blender 4.4+), or of a legacy action
    if getattr(action,'is_action_layered',False):
        if slot is None:return []
        curves=[]
        for layer in action.layers:
            for strip in layer.strips:
                if strip.type=='KEYFRAME':
                    bag=strip.channelbag(slot,ensure=False)
                    if bag is not None:curves.extend(bag.fcurves)
        return curves
    return list(action.fcurves)

def validate(snapshot,plan):
    required={'source_rig','target_rig','source_action','source_slot','bake_range','root_source','root_target','required_sources','mapping'}
    if not isinstance(plan,dict) or set(plan)!=required:raise ValueError('Plan must contain exactly: '+', '.join(sorted(required)))
    if any(not isinstance(plan[k],str) or not plan[k] for k in ['source_rig','target_rig','source_action','source_slot','root_source','root_target']):
        raise ValueError('Rig/action/slot/root names must be nonempty strings')
    if not isinstance(plan['bake_range'],list) or len(plan['bake_range'])!=2 or any(type(x) is not int for x in plan['bake_range']) or plan['bake_range'][1]<plan['bake_range'][0]:
        raise ValueError('bake_range must be two ordered integer frames')
    if not isinstance(plan['required_sources'],list) or not plan['required_sources'] or any(not isinstance(x,str) or not x for x in plan['required_sources']):
        raise ValueError('required_sources must declare nonempty bone names')
    if not isinstance(plan['mapping'],list) or not plan['mapping']:raise ValueError('mapping must be nonempty rows')
    findings=[]
    for key in ['source_rig','target_rig','source_action','source_slot']:
        if snapshot.get(key)!=plan[key]:findings.append({'code':'IDENTITY_MISMATCH','field':key,'expected':plan[key],'actual':snapshot.get(key)})
    if plan['source_rig']==plan['target_rig']:findings.append({'code':'SOURCE_EQUALS_TARGET'})
    source=set(snapshot['source_bones']);target=set(snapshot['target_bones'])
    mapping={};targets=set()
    for row in plan['mapping']:
        if not isinstance(row,dict) or set(row)!={'source','target'}:raise ValueError('Mapping rows require source and target only')
        s,t=row['source'],row['target']
        if not isinstance(s,str) or not isinstance(t,str) or not s or not t or t=='None':
            findings.append({'code':'UNPAIRED_ROW','row':row});continue
        if s not in source:findings.append({'code':'SOURCE_BONE_MISSING','bone':s})
        if t not in target:findings.append({'code':'TARGET_BONE_MISSING','bone':t})
        if s in mapping:findings.append({'code':'DUPLICATE_SOURCE','bone':s})
        if t in targets:findings.append({'code':'DUPLICATE_TARGET','bone':t})
        mapping[s]=t;targets.add(t)
    for s in plan['required_sources']:
        if s not in mapping or mapping[s] not in target:findings.append({'code':'REQUIRED_BONE_UNPAIRED','bone':s})
    if mapping.get(plan['root_source'])!=plan['root_target']:findings.append({'code':'ROOT_PAIR_MISMATCH'})
    bounds=snapshot.get('source_keyed_range')
    if not isinstance(bounds,list) or len(bounds)!=2 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in bounds) or bounds[1]<bounds[0]:
        findings.append({'code':'NO_VALID_SOURCE_KEYED_RANGE'})
    elif plan['bake_range'][0]>bounds[0] or plan['bake_range'][1]<bounds[1]:
        findings.append({'code':'BAKE_RANGE_TRUNCATES_SOURCE','source':bounds,'bake':plan['bake_range']})
    if not snapshot.get('source_slot'):findings.append({'code':'SOURCE_SLOT_UNBOUND'})
    return {'status':'FAIL' if findings else 'PASS','findings':findings,
            'paired_rows':len(mapping),'unmapped_source_bones':sorted(source-mapping.keys()),
            'target_rest_fingerprint':snapshot.get('target_rest_fingerprint'),
            'limits':['Declared identities, mapping existence/uniqueness and keyed range coverage only.',
                      'Not semantic bone correctness, root-motion quality, IK/FK, rest alignment, pose fidelity or export proof.',
                      'Unlisted source bones are reported but not required; choose required_sources from the actual motion needs.']}

def capture(plan):
    import bpy
    src=bpy.data.objects.get(plan['source_rig']);dst=bpy.data.objects.get(plan['target_rig'])
    if not src or not dst or src.type!='ARMATURE' or dst.type!='ARMATURE':raise ValueError('Named source and target armatures must exist')
    data=src.animation_data;action=data.action if data else None;slot=data.action_slot if data else None
    times=[float(k.co.x) for curve in curves_for_slot(action,slot) for k in curve.keyframe_points] if action else []
    rest=[{'name':b.name,'parent':b.parent.name if b.parent else None,'matrix':[list(row) for row in b.matrix_local],'deform':b.use_deform} for b in sorted(dst.data.bones,key=lambda b:b.name)]
    return {'source_rig':src.name,'target_rig':dst.name,'source_action':action.name if action else None,
            'source_slot':slot.identifier if slot else None,'source_bones':list(src.data.bones.keys()),
            'target_bones':list(dst.data.bones.keys()),'source_keyed_range':[min(times),max(times)] if times else None,
            'target_rest_fingerprint':hashlib.sha256(json.dumps(rest,sort_keys=True).encode()).hexdigest(),
            'fps':bpy.context.scene.render.fps/bpy.context.scene.render.fps_base,
            'source_object_matrix':[list(row) for row in src.matrix_world],
            'target_object_matrix':[list(row) for row in dst.matrix_world]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--snapshot',type=Path)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    protected=[args.plan]+([args.snapshot] if args.snapshot else [])
    if args.out.resolve() in {x.resolve() for x in protected} or (args.out.exists() and any(args.out.samefile(x) for x in protected)):
        raise ValueError('Output overlaps plan/snapshot')
    plan=json.loads(args.plan.read_text(encoding='utf-8-sig'))
    snapshot=json.loads(args.snapshot.read_text(encoding='utf-8-sig')) if args.snapshot else capture(plan)
    if not args.snapshot:
        import bpy
        if bpy.data.filepath and (args.out.resolve()==Path(bpy.data.filepath).resolve() or (args.out.exists() and args.out.samefile(bpy.data.filepath))):
            raise ValueError('Output overlaps loaded blend')
    report=validate(snapshot,plan);report['snapshot']=snapshot
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2),encoding='utf8')
    if report['status']!='PASS':raise RuntimeError('ARP retarget preflight failed; inspect report')
    print('ARP_RETARGET_PREFLIGHT_OK')
if __name__=='__main__':main()
