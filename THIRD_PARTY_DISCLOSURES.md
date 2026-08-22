# Third-party dependencies & attribution

SplitShield is built on open source. Direct dependencies and licenses:

## Backend (Python)

| Package | License | Use |
| --- | --- | --- |
| FastAPI | MIT | HTTP API framework |
| Starlette | BSD-3-Clause | ASGI toolkit (FastAPI dependency) |
| Uvicorn | BSD-3-Clause | ASGI server |
| Pydantic / pydantic-settings | MIT | validation & configuration |
| Pillow | MIT-CMU (HPND) | image decoding & processing |
| ImageHash | BSD-2-Clause | perceptual hashing (pHash) |
| PyWavelets | MIT | ImageHash dependency |
| NumPy | BSD-3-Clause | numeric core |
| SciPy | BSD-3-Clause | scientific routines |
| scikit-learn | BSD-3-Clause | k-NN search, logistic regression, metrics |
| httpx | BSD-3-Clause | test client transport |
| pytest / pytest-asyncio | MIT / Apache-2.0 | test suite |
| python-multipart | Apache-2.0 | upload parsing |

Optional (auto-detected, not required):

| Package | License | Use |
| --- | --- | --- |
| PyTorch | BSD-3-Clause | learned embedding backend |
| torchvision | BSD-3-Clause | MobileNetV3-Small (ImageNet-1k weights) |

## Frontend (JavaScript/TypeScript)

| Package | License | Use |
| --- | --- | --- |
| Next.js | MIT | React framework |
| React / React DOM | MIT | UI |
| Tailwind CSS | MIT | styling |
| Recharts | MIT | charts |
| TypeScript | Apache-2.0 | type checking |
| ESLint (+ next config) | MIT | linting |
| @playwright/test | Apache-2.0 | end-to-end tests |

## Methodological attribution

* **pHash**: DCT-based perceptual hashing as popularised by the pHash project
  (Zauner, 2010) via the `ImageHash` implementation.
* **MobileNetV3**: Howard et al., *Searching for MobileNetV3*, ICCV 2019;
  ImageNet-1k pretrained weights from torchvision (when available).
* **HOG-style gradient features** in the classical descriptor follow Dalal &
  Triggs, CVPR 2005.
* **Related tools acknowledged**: FiftyOne (Voxel51, Apache-2.0),
  CleanVision (Cleanlab Inc., AGPL-3.0), Cleanlab (AGPL-3.0). SplitShield
  shares no code with these projects; they are cited as prior art for
  duplicate detection.

## Demo dataset

Generated programmatically at runtime from geometric primitives with a fixed
seed. It contains no third-party imagery and no depictions of people.
