"""균일 배율 모델 루트 기준으로 광원의 위치·크기·세기 초기값을 변환한다."""
import copy
import math


def normalize_lights(lights,root):
    columns=[[root[i][j] for i in range(3)] for j in range(3)]
    scales=[math.sqrt(sum(v*v for v in col)) for col in columns]
    scale=scales[0]
    if scale<=0 or max(scales)-min(scales)>1e-5:
        raise ValueError("균일한 양수 루트 배율이 필요하다.")
    if any(abs(sum(a*b for a,b in zip(columns[i],columns[j])))>1e-5 for i in range(3) for j in range(i)):
        raise ValueError("전단이 있는 루트는 별도 조명 보정이 필요하다.")
    inverse=[[root[j][i]/(scale*scale) for j in range(3)]+[0] for i in range(3)]+[[0,0,0,1]]
    for i in range(3):
        inverse[i][3]=-sum(inverse[i][j]*root[j][3] for j in range(3))
    result=copy.deepcopy(lights)
    for source,target in zip(lights,result):
        target["matrix_world"]=[[sum(inverse[i][k]*source["matrix_world"][k][j] for k in range(4)) for j in range(4)] for i in range(4)]
        target["energy"]=source["energy"]/(scale*scale)
        target["size"]=source["size"]/scale
        target["size_y"]=source["size_y"]/scale
        target["source_power"]=source["energy"]
        target["source_root_scale"]=scale
    return result
