# NVIDIA product landscape — disambiguation & entry points

**Purpose:** orient fast and pick the right product + where to look. This is a map, **not ground
truth** — always confirm specifics (versions, APIs, support) from the live source you retrieve.
Product identities below are stable; details change. If the user's target is ambiguous, resolve it
here first, then search.

The canonical hub for most products is `https://developer.nvidia.com/<slug>` (links to docs,
downloads, getting-started). Docs live under `https://docs.nvidia.com/...`. Code lives in NVIDIA
GitHub orgs; models in the `nvidia` Hugging Face org.

## Inference & model serving
| Product | What it is | Entry point |
|---|---|---|
| **TensorRT** | Optimizing inference runtime/compiler for NNs on NVIDIA GPUs | `developer.nvidia.com/tensorrt`, `docs.nvidia.com/deeplearning/tensorrt/` |
| **TensorRT-LLM** | LLM-specific inference optimization library on top of TensorRT | `developer.nvidia.com/tensorrt-llm`, GitHub `NVIDIA/TensorRT-LLM` |
| **Triton Inference Server** | Multi-framework model-serving server | `developer.nvidia.com/triton-inference-server`, org `triton-inference-server` |
| **Dynamo** | Datacenter-scale distributed inference serving framework | `developer.nvidia.com/dynamo` |
| **NIM (NVIDIA Inference Microservices)** | Containerized, API-first inference microservices for prebuilt models | `developer.nvidia.com/nim`, `build.nvidia.com` |

## LLM / generative-AI frameworks
| Product | What it is | Entry point |
|---|---|---|
| **NeMo** | Framework for building/training/customizing LLMs, speech & multimodal models | `developer.nvidia.com/nemo`, `docs.nvidia.com/nemo/` |
| **NeMo Guardrails** | Toolkit for programmable safety/guardrails on LLM apps | GitHub `NVIDIA-NeMo/Guardrails` (moved from `NVIDIA/NeMo-Guardrails`; old URL redirects) |
| **NeMo Retriever / Blueprints** | Enterprise RAG & agent reference blueprints | `build.nvidia.com`, developer blog |
| **Cosmos** | World-foundation-model platform for physical AI / synthetic data | `developer.nvidia.com/cosmos` |

## Speech & language
| Product | What it is | Entry point |
|---|---|---|
| **Riva** | SDK for speech AI (ASR, TTS) and translation | `developer.nvidia.com/riva` |
| (models) | Parakeet/Canary (ASR), etc. are NeMo/Riva models | HF `huggingface.co/nvidia` |

## Vision, video & sensor AI
| Product | What it is | Entry point |
|---|---|---|
| **DeepStream** | SDK for real-time video analytics / streaming AI pipelines | `developer.nvidia.com/deepstream-sdk` |
| **Metropolis** | Platform/ecosystem for vision AI & IVA (includes DeepStream, TAO) | `developer.nvidia.com/metropolis` |
| **DALI** | GPU-accelerated data loading & augmentation for training/inference | `developer.nvidia.com/dali` |
| **Maxine** | SDK for AI-enhanced audio/video (real-time effects) | `developer.nvidia.com/maxine` |

## Robotics & simulation
| Product | What it is | Entry point |
|---|---|---|
| **Isaac Sim** | Robotics simulation on Omniverse | `developer.nvidia.com/isaac-sim` |
| **Isaac ROS** | Hardware-accelerated ROS 2 packages | `developer.nvidia.com/isaac-ros`, org `NVIDIA-ISAAC-ROS` |
| **Omniverse** | Platform for 3D simulation, digital twins, OpenUSD | `developer.nvidia.com/omniverse`, org `NVIDIA-Omniverse` |
| **Holoscan** | SDK for real-time sensor/streaming AI (medical, edge) | `developer.nvidia.com/holoscan-sdk`, `docs.nvidia.com/holoscan/` |

## HPC / CUDA core & libraries
| Product | What it is | Entry point |
|---|---|---|
| **CUDA Toolkit** | Core GPU compute platform, compiler, runtime | `developer.nvidia.com/cuda-toolkit` |
| **cuDNN** | Deep-learning primitives library | `developer.nvidia.com/cudnn` |
| **NCCL** | Multi-GPU/multi-node collective communication library | `developer.nvidia.com/nccl` |
| **CUTLASS** | CUDA templates for high-performance GEMM/linear algebra | `docs.nvidia.com/cutlass/`, GitHub `NVIDIA/cutlass` |
| **Nsight Systems/Compute** | Profiling & performance analysis tools | `developer.nvidia.com/nsight-systems` |

## Data science, recommenders, security, edge
| Product | What it is | Entry point |
|---|---|---|
| **RAPIDS** (cuDF, cuML, cuGraph) | GPU-accelerated data science / ML (pandas/scikit-like APIs) | `developer.nvidia.com/rapids`, org `rapidsai` |
| **Merlin** | GPU-accelerated recommender-system framework | `developer.nvidia.com/merlin`, org `NVIDIA-Merlin` |
| **Morpheus** | GPU-accelerated cybersecurity AI framework | `developer.nvidia.com/morpheus` |
| **Jetson** | Embedded/edge modules & the JetPack SDK | `developer.nvidia.com/embedded/jetson-modules`, org `NVIDIA-AI-IOT` |

## Commonly confused — resolve before searching
- **TensorRT vs. TensorRT-LLM:** TensorRT is the general inference compiler/runtime; TensorRT-LLM
  is the LLM-focused library built on it. "Optimize my LLM" → TensorRT-LLM.
- **Triton (Inference Server) vs. other "Triton":** here Triton means NVIDIA's model-serving
  server. It is unrelated to OpenAI's Triton GPU kernel language — if the user is writing GPU
  kernels, that's a different tool; confirm which they mean.
- **NIM vs. NGC vs. build.nvidia.com:** NIM = deployable inference *microservices*; NGC catalog =
  registry of models/containers/charts; build.nvidia.com = the API catalog/playground where you
  try NIMs and hosted model endpoints.
- **NeMo (framework) vs. "nemo":** NVIDIA NeMo is the generative-AI framework; ignore unrelated
  projects named "nemo". NeMo Guardrails and NeMo Retriever are distinct components under NeMo.
- **Metropolis vs. DeepStream:** Metropolis is the umbrella vision-AI platform; DeepStream is the
  streaming-video-analytics SDK within it.
- **Isaac Sim vs. Isaac ROS:** Sim = simulation environment (Omniverse); ROS = accelerated ROS 2
  runtime packages for real robots.
- **CUDA vs. cuDNN vs. NCCL vs. CUTLASS:** CUDA = the platform; cuDNN = DL primitives; NCCL =
  multi-GPU communication; CUTLASS = GEMM/linear-algebra templates. Match to the user's layer.

When you're unsure a product still exists or hasn't been renamed/superseded, **search before
answering** — retire nothing and invent nothing from this list without confirming against a live
page.
