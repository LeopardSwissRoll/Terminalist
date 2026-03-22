아직 `Phase A 완료`라고 보긴 어렵습니다. 내 기준으로는 `Phase A scaffolding` 정도입니다.

**Findings**
1. 계획서의 필수 산출물 중 핵심이 빠져 있습니다. `Phase A` 는 `InputEvent`, `Cell/Rect/Frame`, `LayoutNode`, `FrontendAction 또는 action dispatch 규약` 추출이 목표인데, 현재는 `Cell`, `Rect`, `LayoutNode` 쪽만 있습니다. [textual-exit-plan.md](/c:/Users/jsy/Desktop/MultiTerm/docs/textual-exit-plan.md#L318) [cells.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/frontend/cells.py#L13) [layout.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/frontend/layout.py#L14)

2. 가장 중요한 경계인 `frontend/input_backend.py` 가 아직 없습니다. 그래서 새 frontend가 써야 할 `InputEvent` 계약도 없고, Textual 제거의 핵심 이유였던 입력 계층 분리도 아직 frontend 쪽으로 넘어오지 않았습니다. [textual-exit-plan.md](/c:/Users/jsy/Desktop/MultiTerm/docs/textual-exit-plan.md#L225)

3. 입력 백엔드 구현은 여전히 Textual에 묶여 있습니다. 현재 실제 구현은 [terminalist/drivers/input_backends.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/drivers/input_backends.py#L25) 에 있고, `textual.constants`, `XTermParser`, `Resize`, `Message` 를 직접 씁니다. 이 상태에선 “Textual 없이 import 가능한 frontend core”라는 경계가 아직 성립하지 않습니다.

4. `Frame` 도 아직 명시적 타입으로 추출되지 않았습니다. 지금은 [compositor.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/frontend/compositor.py#L69) 안에서 사실상 `list[list[Cell]]` 로 암묵 처리되고 있어서, 이후 `screen_sync`/`chrome`/`overlays` 와 맞물릴 공용 계약이 비어 있습니다.

좋은 쪽도 분명합니다. [cells.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/frontend/cells.py#L13), [layout.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/frontend/layout.py#L14), [compositor.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/frontend/compositor.py#L69) 는 Textual 없이 import 가능했고, 방향 자체는 맞습니다. 다만 이건 `Phase A 완료`보다는 `Phase A의 절반 이상 착수`에 가깝습니다.

내 판정은 이겁니다:  
`완료 아님. 50~60% 정도.`

다음으로 바로 해야 할 건 3개입니다.

1. `terminalist/frontend/input_backend.py` 추가 후 `InputEvent` 정의  
2. `terminalist/drivers/input_backends.py` 의 Textual 의존 제거 또는 frontend 쪽으로 이동  
3. `FrontendAction` 혹은 `input_router` 가 소비할 최소 action 계약 정의

이 세 개가 들어가면 그때는 `Phase A 완료`라고 불러도 됩니다.