# 以 vLLM 为代表的 AI Infra Systems 论文综述

> 阶段产物：DeepSeek v4 Pro 结构化草稿；尚待 Codex GPT 最终审查。

> 研究轮次：第 1 轮；本轮论文：32 篇；累计论文：32 篇；生成时间：2026-08-14T08:57:11.237808+00:00。

## 摘要

本综述系统梳理了 AI Infra 系统中以大模型在线推理为核心的技术演进，涵盖内存管理、请求调度、并行执行、低精度计算及可靠性等核心优化维度。通过分析 32 篇通过验证的学术论文，我们构建了各领域的技术演化脉络，揭示了从基础分页内存管理到动态跨实例调度、从均匀量化到自适应低精度计算、从静态配置到可靠性与能耗感知的系统级优化趋势。综述强调了跨层协同设计的重要性，并指出了当前研究在分布式确定性、长上下文效率、多维度权衡及实测负载覆盖等方面的不足，为未来 AI Infra Systems 的研究提供了系统性参考。

## 范围与方法

本综述以 vLLM 引领的 AI Infra Systems 为对象，围绕内存管理、请求调度、并行执行、低精度计算、软硬件协同等核心问题，对 32 篇经验证的论文报告进行了结构化综合分析。我们根据论文的技术贡献与演化关系，将其划分为六大类别：推理服务与请求调度、KV Cache 与内存管理、并行计算与分布式执行、训练系统与优化、模型压缩与低精度计算、性能评测与成本分析、以及可靠性、弹性与可观测性。通过在每个类别内构建技术进化线程，明确区分直接改进、机制扩展、替代方案、正交工作和评估研究，并在类别间建立横向关联与全局趋势，最终综合形成对 AI Infra Systems 技术发展脉络的全面叙事。

## 分类综述

### 推理服务与请求调度

该类别聚焦于LLM推理服务中的请求调度与资源分配优化，覆盖从单GPU内部到跨实例的调度机制演进，旨在提升吞吐、降低延迟并满足SLO。早期工作通过单机内细粒度并行与nano-batch重叠提升吞吐 [P05]，后续研究扩展至单机内的prefill/decode解耦 [P15]、混合实时/尽力而为请求调度 [P16]、公平性感知的上下文切换优化 [P12]、以及前缀缓存局部性感知的公平调度 [P13]。跨实例层面，动态请求迁移与全局队列管理等机制被提出以应对负载不均和SLO达成 [P06][P27]，并进一步统一共置与分离式执行 [P14]。整体上，调度从静态粗粒度向动态细粒度、从吞吐中心向SLO和公平性敏感演进。

主分类论文：[P05], [P06], [P12], [P13], [P14], [P15], [P16], [P27]

#### 技术演进主线：单机内请求调度优化

**主线问题：** 如何通过单机内的调度与资源分配机制优化LLM推理服务的吞吐与延迟？

该线程从P05的nano-batch流水线与intra-device parallelism奠定高吞吐基础 [P05]，随后通过机制扩展引入prefill/decode解耦 [P15]、混合请求优先级调度 [P16]、公平性感知的上下文切换优化 [P12]和前缀缓存局部性感知的公平调度 [P13]。其中，P15针对混合批次干扰问题动态划分SM，实现阶段逻辑分离 [P15]；P16提出迭代级优先级调度与双向KV块共享，平衡实时与尽力而为请求 [P16]；P12通过块组KV缓存和异步交换降低抢占式切换开销 [P12]；P13则在公平调度中纳入前缀缓存局部性，以赤字机制保障公平性与缓存复用 [P13]。这些工作共同丰富了单机内调度策略，在吞吐、延迟、公平性等维度上形成互补。

##### 1. [P05] NanoFlow: Towards Optimal Large Language Model Serving Throughput

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：LLM在线推理服务中，单GPU内计算、内存和网络操作顺序执行，导致资源利用率低、吞吐远低于理论最优。
- 本作贡献或改进：提出NanoFlow框架，通过nano-batch流水线与intra-device parallelism重叠异构资源操作，自动搜索最优执行管线，显著提升端到端吞吐并接近理论最优。
- 代价与权衡：收益依赖精确的调度与资源分配；仅拆分nano-batch而不重叠会导致性能下降；KV-cache分层卸载引入约3%的pipeline开销。
- 剩余问题：未覆盖prefill/decode混合干扰问题，未处理异构QoS需求，未优化上下文切换开销。
- 关系依据：作为基础工作，P05提出了单机内资源重叠与细粒度并行的核心机制，为后续调度优化提供了性能基准和机制起点 [P05]。

##### 2. [P15] Nexus:Proactive Intra-GPU Disaggregation of Prefill and Decode in LLM Serving

- 关系类型：机制扩展
- 承接论文：[P05]
- 前作问题：P05虽提升了吞吐，但未解决prefill与decode在混批时的细粒度干扰，导致TBT延迟显著升高。
- 本作贡献或改进：在单GPU内通过动态SM分区实现prefill/decode的逻辑解耦，结合成本模型和滞回控制，同时降低TTFT/TBT并保持高吞吐。
- 代价与权衡：需要离线profiling标定模型参数；在输入长度多样性高或均匀的特定工作负载下，延迟改善不显著。
- 剩余问题：仍未针对混合实时/尽力而为请求的优先级调度需求进行优化。
- 关系依据：P15扩展了P05的单机内资源重叠思想，通过动态SM分区将并行性从单纯的计算/内存重叠延伸到prefill/decode阶段解耦，是对P05机制的进一步延伸 [P05] [P15]。

##### 3. [P16] Efficient LLM Serving on Hybrid Real-time and Best-effort Requests

- 关系类型：正交工作
- 承接论文：[P05]
- 前作问题：P05假设请求优先级均匀，但实际服务中需同时服务实时（RT）与尽力而为（BE）请求，存在异构QoS需求。
- 本作贡献或改进：提出BROS，通过迭代级动态优先级调度与双向KV缓存块共享，在共置RT/BE请求的同时降低RT延迟、提升SLO达成率，并保持BE吞吐。
- 代价与权衡：BE吞吐有约10-18%的下降；BE请求数据集为合成，可能不完全反映真实分布。
- 剩余问题：未解决上下文切换开销问题，且未结合前缀缓存局部性。
- 关系依据：P16与P05在单机调度空间内正交：P05优化均匀优先级下的吞吐，P16则面向混合QoS的调度与缓存共享，两者无直接改进关系 [P05] [P16]。

##### 4. [P12] FastSwitch: Optimizing Context Switching Efficiency in Fairness-aware Large Language Model Serving

- 关系类型：正交工作
- 承接论文：[P05], [P16]
- 前作问题：公平性驱动的LLM服务中，优先级调整导致上下文切换开销大，I/O利用率低、GPU空闲，且多轮对话存在冗余I/O。
- 本作贡献或改进：提出FastSwitch，通过动态块组KV缓存管理、多线程异步交换和跨轮次KV缓存复用，显著降低抢占式上下文切换开销，改进TTFT/TBT。
- 代价与权衡：实验覆盖模型和硬件有限，优先级在线生成和真实trace验证不足。
- 剩余问题：未将前缀缓存局部性纳入公平调度考量。
- 关系依据：P12针对上下文切换这一特定瓶颈进行优化，与P05的nano-batch重叠和P16的混合请求调度均正交，无直接改进关系 [P05] [P12] [P16]。

##### 5. [P13] Locality-aware Fair Scheduling in LLM Serving

- 关系类型：机制扩展
- 承接论文：[P12], [P16]
- 前作问题：P12优化了上下文切换效率，但未考虑前缀缓存局部性；P16处理了优先级调度但未提供公平性保证。
- 本作贡献或改进：提出局部性感知的公平调度算法DLPM及其分布式版本D2LPM，通过赤字机制在保持前缀缓存局部性的同时提供公平性保证，提升吞吐并降低客户端延迟。
- 代价与权衡：仅考虑同一客户端内部的前缀共享，忽略跨客户端共享；未处理程序内请求间数据依赖。
- 剩余问题：分布式场景下公平性与局部性的权衡仍需进一步优化。
- 关系依据：P13在公平调度思想上是P12的机制扩展，将前缀缓存局部性纳入公平调度；同时与P16的优先级调度互补，但通过结合局部性提升整体性能，无直接改进关系 [P12] [P13] [P16]。

#### 技术演进主线：跨实例动态请求调度

**主线问题：** 如何通过跨实例的动态请求调度与迁移优化LLM推理服务的负载均衡、SLO达成与成本效率？

该线程从P06的KV cache实时迁移与虚拟用量调度奠定基础 [P06]，随后P27提出基于请求等待时间估计的全局队列管理作为替代方案 [P27]，P14则通过micro-request抽象与两级调度统一共置与分离式执行，融合了前两者思想并进一步扩展 [P06][P14][P27]。整体从最初的迁移机制演进到更细粒度的请求切分与全局优化，不断提升SLO达成率和资源利用率。

##### 1. [P06] Llumnix: Dynamic Scheduling for Large Language Model Serving

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：LLM推理服务中异构、不可预测请求导致负载不均、内存碎片和优先级干扰，传统一次性分发无法动态应对。
- 本作贡献或改进：提出Llumnix，通过KV cache实时迁移实现跨实例请求重调度，统一负载均衡、去碎片化、优先级隔离和自动扩缩容，显著改善尾延迟、高优先级加速和成本效率。
- 代价与权衡：仅支持vLLM后端，优先级仅分两类，virtual usage规则简单。
- 剩余问题：未探索基于队列等待时间的全局调度方法，且缺乏更细粒度的请求切分机制。
- 关系依据：P06开创了基于KV cache迁移的跨实例动态调度，是该线程的基础性工作 [P06]。

##### 2. [P27] Queue management for slo-oriented large language model serving

- 关系类型：横向替代
- 承接论文：[P06]
- 前作问题：P06通过迁移实现调度，但可能带来迁移开销和复杂度；需要一种更轻量、基于队列的SLO导向调度方法。
- 本作贡献或改进：提出QLM，通过请求等待时间（RWT）估计器预测队列等待时间，由全局调度器执行请求拉取、驱逐、负载均衡和模型切换，提升SLO达成率与吞吐。
- 代价与权衡：RWT估计器在请求组较少时会高估等待时间；输出长度极端值下可能低估完成时间；不支持抢占式负载均衡。
- 剩余问题：缺乏请求的动态迁移能力，无法在任意token边界灵活切分请求。
- 关系依据：P27采用基于队列管理的替代方法实现SLO导向调度，与P06的KV cache迁移机制形成替代关系，两者无直接改进关系 [P06] [P27]。

##### 3. [P14] DynaServe: Unified and Elastic Execution for Dynamic Disaggregated LLM Serving

- 关系类型：机制扩展
- 承接论文：[P06], [P27]
- 前作问题：P06的迁移粒度为整个请求，P27的队列管理粒度较粗，均无法在任意token边界灵活切分请求以实现最优资源利用。
- 本作贡献或改进：提出DynaServe，通过micro-request抽象（可在任意token边界切分请求）和两级调度，统一共置与分离式执行，在满足SLO的同时最大化GPU利用率。
- 代价与权衡：未专门评估超长上下文或大规模集群；输出长度预测依赖现有方法，极端误差下SLO保证不充分。
- 剩余问题：对超长上下文和更大规模集群的扩展性仍需研究。
- 关系依据：P14扩展了P06的跨实例调度灵活性，利用类似迁移的思想进行chunk-based KV传输，同时结合P27的队列与调度控制思想，通过更细粒度的请求切分和统一放置机制提升了能力 [P06] [P14] [P27]。

#### 横向与跨主线联系

- P01的PagedAttention提供了KV cache分页管理基础，被P05、P06等调度系统广泛采用 [P01]。
- P02的RadixAttention前缀缓存复用与P13的前缀缓存局部性调度直接相关 [P02][P13]。
- P03的vAttention虚拟内存管理为单机内KV cache分配提供了替代方案，与P05等资源重叠方法互补 [P03][P05]。
- P04的BurstGPT真实负载数据集被P06、P14等用于驱动动态调度评估 [P04][P06][P14]。
- P11的Pensieve多级KV缓存保存与P16的双向KV共享相关 [P11][P16]。
- P23的OrbitFlow细粒度KV重配置与P14的micro-request切分类似，均面向动态长上下文服务 [P23][P14]。

#### 分类趋势

- 从单机内吞吐优化向跨实例SLO和公平性敏感调度演进 [P05][P06][P13]。
- 调度粒度不断细化：从nano-batch到micro-request，支持任意边界切分 [P05][P14]。
- prefill/decode解耦成为降低延迟的关键技术路径，从跨实例分离式发展到单GPU内动态SM分区 [P06][P15]。
- KV缓存管理与调度深度耦合，从简单复用发展到双向共享和局部性感知公平调度 [P01][P16][P13]。
- 越来越多系统采用动态、运行时反馈驱动的调度策略，以应对不可预测负载 [P06][P15][P27]。

### KV Cache与内存管理

KV Cache与内存管理领域聚焦于大语言模型推理中键值缓存的高效存储、分配、压缩与复用，核心挑战包括消除碎片、扩展容量、提升带宽利用率，并协同调度以优化吞吐与延迟 [P01] [P11] [P19]。

主分类论文：[P01], [P02], [P03], [P09], [P11], [P17], [P18], [P19], [P20], [P21], [P22], [P23], [P24]

#### 技术演进主线：GPU内存动态管理与分页机制

**主线问题：** 如何高效管理GPU上的KV缓存内存以减少空闲并支持动态分配？

该线程从PagedAttention引入分页思想开始，通过非连续物理块和块表管理KV缓存，实现近零碎片并支持共享 [P01]。随后vAttention利用CUDA虚拟内存保留虚拟连续性，避免内核重写，成为替代路线 [P03]。vToken则在块管理之上增加token级虚拟化，通过间接寻址回收块内碎片，是对PagedAttention的机制扩展 [P24]。

##### 1. [P01] Efficient Memory Management for Large Language Model Serving with PagedAttention

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：LLM serving中KV缓存采用连续预分配，导致大量内存浪费（仅20.4%-38.2%被有效使用），且无法动态共享。
- 本作贡献或改进：提出PagedAttention，将KV缓存划分为固定大小的非连续物理块，通过块表映射实现按需分配和块粒度共享，几乎消除内部和外部碎片。
- 代价与权衡：引入块表间接寻址和内核重写，使注意力内核延迟比FasterTransformer高20-26%；对计算密集型负载可能不带来性能提升。
- 剩余问题：块映射增加内核开销，且未解决token级驱逐导致的块内碎片问题。
- 关系依据：P01是首个系统化解决KV缓存内存浪费的工作，为后续研究奠定基础 [P01]。

##### 2. [P03] vAttention: Dynamic Memory Management for Serving LLMs without PagedAttention

- 关系类型：横向替代
- 承接论文：[P01]
- 前作问题：PagedAttention需要重写注意力内核并维护块表，增加编程复杂性和运行时开销，且难以直接利用新型内核。
- 本作贡献或改进：vAttention利用CUDA虚拟内存管理API解耦虚拟与物理内存，保留KV缓存虚拟连续性，按需映射物理页，避免内核重写和块表。
- 代价与权衡：需要修改NVIDIA驱动以支持小页（64KB），否则需使用2MB页导致内部碎片；未实现CPU换出。
- 剩余问题：仅优化GPU内存，未涉及多级存储或token级碎片回收。
- 关系依据：P03明确针对PagedAttention的缺点提出替代方案，通过系统级虚拟内存管理实现动态分配，与P01形成技术路线对比 [P01] [P03]。

##### 3. [P24] vToken: Token-Level Virtualization for Reclaimable KV Caches

- 关系类型：机制扩展
- 承接论文：[P01], [P03]
- 前作问题：在PagedAttention块管理下，token级驱逐导致大量部分存活块无法回收，块内浪费达40-60%。
- 本作贡献或改进：vToken在块管理之上引入token-table间接寻址，解耦逻辑token活跃性与物理块放置，通过异步重打包回收块内碎片，无需修改注意力内核。
- 代价与权衡：异步拷贝可能竞争HBM带宽；仅支持单节点单GPU；保守跳过共享前缀块。
- 剩余问题：未结合量化等表示层优化，且未扩展到分布式场景。
- 关系依据：P24在P01的块管理基础上进行机制扩展，解决token级驱逐与块粒度管理的失配；同时与P03的虚拟内存方法正交，因为它仍使用块级物理管理 [P01] [P03] [P24]。

#### 技术演进主线：跨存储层级与设备间KV缓存管理

**主线问题：** 如何利用CPU、SSD和共享内存等多级存储扩展KV缓存容量并优化数据移动？

Pensieve首先提出GPU/CPU多级缓存并扩展PagedAttention支持多token注意力，奠定基础 [P11]。随后Strata通过GPU辅助I/O和缓存感知调度优化碎片化分层加载 [P19]。AdaptCache引入有损压缩和自适应设备放置 [P20]，EVICPRESS联合优化压缩与驱逐 [P21]，VeriCache用压缩草稿+全量验证实现无损输出 [P22]。Tutti将KV缓存扩展到SSD并消除CPU干预 [P17]，TraCT利用CXL共享内存实现机架级缓存 [P18]，OrbitFlow精细优化请求级放置以保障SLO [P23]。

##### 1. [P11] Stateful Large Language Model Serving with Pensieve

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：多轮对话中反复重算历史导致低效，且GPU内存不足以容纳所有KV缓存。
- 本作贡献或改进：Pensieve提出状态化服务，利用GPU/CPU多级KV缓存跨请求复用，并扩展PagedAttention支持非连续内存上的多token注意力。
- 代价与权衡：CPU缓存引入PCIe传输延迟，需流水线隐藏；未覆盖远程存储或流式传输。
- 剩余问题：仅利用本地GPU/CPU内存，未扩展到SSD或共享内存。
- 关系依据：P11是首个系统化利用多级存储扩展KV缓存容量的工作，为后续跨层级管理提供基础 [P11]。

##### 2. [P19] Strata: Hierarchical Context Caching for Long Context Language Model Serving

- 关系类型：机制扩展
- 承接论文：[P11]
- 前作问题：长上下文服务中，碎片化KV缓存从CPU/外部存储加载带宽利用率低，且调度未将I/O视为一等资源。
- 本作贡献或改进：Strata提出GPU辅助I/O内核和缓存感知调度，将碎片化加载与计算重叠，提升带宽利用并降低TTFT。
- 代价与权衡：GPU辅助I/O仍有开销；未充分评估磁盘缓存；仅限单实例。
- 剩余问题：未跨实例整合KV缓存池。
- 关系依据：P19在P11的多级缓存思想基础上，针对碎片化加载和调度进行优化，是对P11的机制扩展 [P11] [P19]。

##### 3. [P20] AdaptCache: KV Cache Native Storage Hierarchy for Low-Delay and High-Quality Language Model Serving

- 关系类型：机制扩展
- 承接论文：[P11], [P19]
- 前作问题：多层存储中固定压缩策略导致部分KV缓存被迫放置于慢速SSD，增加延迟。
- 本作贡献或改进：AdaptCache提出有损KV缓存压缩，自适应选择压缩算法、压缩率和设备放置，提高DRAM命中率。
- 代价与权衡：贪婪算法不保证最优；尚未大规模部署评估。
- 剩余问题：压缩与驱逐决策独立，未联合优化。
- 关系依据：P20在P11和P19多级存储基础上引入有损压缩维度，扩展了管理手段 [P11] [P19] [P20]。

##### 4. [P21] EVICPRESS: Joint KV-Cache Compression and Eviction for Efficient LLM Serving

- 关系类型：直接改进
- 承接论文：[P20]
- 前作问题：AdaptCache固定压缩策略且驱逐与压缩独立决策，无法根据上下文敏感度优化质量与延迟。
- 本作贡献或改进：EVICPRESS提出统一效用函数，联合优化压缩与驱逐决策，显著降低TTFT或提升质量。
- 代价与权衡：依赖带宽稳定假设；仅单节点评估；压缩方法有限。
- 剩余问题：未扩展到多节点或量化等更丰富压缩方法。
- 关系依据：P21直接针对P20的固定压缩和独立决策的缺点进行改进，实现联合优化，是对P20的直接改进 [P20] [P21]。

##### 5. [P22] VeriCache: Turning Lossy KV Cache into Lossless LLM Inference

- 关系类型：机制扩展
- 承接论文：[P20], [P21]
- 前作问题：有损压缩会破坏输出质量，无法保证与全量KV解码一致。
- 本作贡献或改进：VeriCache将有损压缩KV缓存作为草稿生成器，再用全量KV验证，实现无损输出并提升吞吐。
- 代价与权衡：需要保留全量KV缓存，增加存储开销；固定草稿长度。
- 剩余问题：未扩展到其他有损技术或自适应草稿长度。
- 关系依据：P22在P20/P21的有损压缩基础上引入验证机制，保证输出无损，是对该路线的机制扩展 [P20] [P21] [P22]。

##### 6. [P17] Tutti: Making SSD-Backed KV Cache Practical for Long-Context LLM Serving

- 关系类型：机制扩展
- 承接论文：[P11]
- 前作问题：现有SSD-backed缓存依赖CPU进行I/O控制，限制带宽并增加延迟。
- 本作贡献或改进：Tutti提出GPU中心化的SSD对象存储，通过GPU io_uring和slack-aware调度消除CPU干预，接近DRAM性能。
- 代价与权衡：跨节点远程路径尚未优化；分布式评估有限。
- 剩余问题：未实现GPU-initiated RDMA直通远程路径。
- 关系依据：P17将P11的设备扩展思想推进到SSD层级，并优化I/O路径，是P11的机制扩展 [P11] [P17]。

##### 7. [P18] TraCT: Disaggregated LLM Serving with CXL Shared Memory KV Cache at Rack-Scale

- 关系类型：正交工作
- 承接论文：[P11]
- 前作问题：机架级解耦服务中KV缓存跨节点传输依赖RDMA，引入高延迟和网络跳数。
- 本作贡献或改进：TraCT利用CXL共享内存作为机架级KV缓存和传输层，通过load/store和DMA直接访问，消除RDMA跳数。
- 代价与权衡：依赖CXL Type-3硬件且缺乏硬件原子操作；仅两节点评估；朴素LRU。
- 剩余问题：需更复杂替换策略和生产级多节点验证。
- 关系依据：P18采用共享内存方法，与P11基于本地存储层级的思路正交，但其扩展了设备边界 [P11] [P18]。

##### 8. [P23] OrbitFlow: SLO-Aware Long-Context LLM Serving with Fine-Grained KV Cache Reconfiguration

- 关系类型：机制扩展
- 承接论文：[P11], [P19]
- 前作问题：长上下文推理中，请求级KV缓存放置未依据SLO动态优化，导致SLO违规和吞吐下降。
- 本作贡献或改进：OrbitFlow通过轻量级ILP求解器为每个请求按层动态决定GPU/CPU放置，结合Token-Deposit和Pause-Resume提升SLO达成率。
- 代价与权衡：仅支持单节点多GPU；严重过载时无法保证所有SLO；搜索剪枝有微小性能损失。
- 剩余问题：未扩展跨节点流水线并行。
- 关系依据：P23结合P11的多级缓存和P19的调度思想，在请求级精细优化放置，是两者的机制扩展 [P11] [P19] [P23]。

#### 技术演进主线：结构化复用与请求调度优化

**主线问题：** 如何通过缓存共享与调度策略提升多请求场景下的吞吐和延迟？

SGLang的RadixAttention通过radix-tree管理KV缓存，实现自动前缀复用并影响调度，成为该线程基础 [P02]。CacheBlend则通过选择性重计算融合非前缀缓存，扩展了复用范围 [P09]。

##### 1. [P02] SGLang: Efficient Execution of Structured Language Model Programs

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：多调用LM程序中存在大量共享前缀，但现有系统无法有效复用KV缓存，导致冗余prefill。
- 本作贡献或改进：提出RadixAttention，将KV缓存组织为radix tree的LRU缓存，支持自动前缀复用和缓存感知调度。
- 代价与权衡：缓存感知调度可能导致饥饿；无复用机会时管理开销小于0.3%。
- 剩余问题：尚未与非前缀复用有效结合。
- 关系依据：P02首次将KV缓存作为结构化缓存管理，为前缀复用和调度优化奠定基础 [P02]。

##### 2. [P09] CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion

- 关系类型：机制扩展
- 承接论文：[P02]
- 前作问题：RAG场景中多个非前缀文本块无法直接复用KV缓存，需完整prefill，导致高TTFT。
- 本作贡献或改进：CacheBlend通过选择性KV重计算融合预计算的非前缀KV缓存，恢复cross-attention并降低TTFT。
- 代价与权衡：仅适用于transformer架构；未在最新serving引擎上测试。
- 剩余问题：未处理跨节点共享或量化设置。
- 关系依据：P09扩展了P02的前缀复用思想，通过选择性重计算支持非前缀缓存融合 [P02] [P09]。

#### 横向与跨主线联系

- P04的BurstGPT提供真实工作负载数据集，可用于评估KV缓存管理策略在实际负载下的效果 [P04]。
- P10的CacheGen针对KV缓存传输进行压缩和流式传输，与多级存储中的压缩技术互补 [P10]。
- P07的KIVI提出2bit量化KV缓存，可进一步减少内存占用，与有损压缩策略形成权衡 [P07]。
- P25的MiniKV通过逐层差异化量化，与P20/P21的有损压缩思路相关但更侧重准确率保持 [P25]。
- P26的Oaken提出混合量化与定制引擎，是KV缓存压缩的另一个软硬件协同方向 [P26]。
- P12的FastSwitch关注抢占式调度中的上下文切换，其KV缓存管理策略与调度优化密切相关 [P12]。
- P13的局部性感知公平调度利用前缀缓存局部性，与RadixAttention的缓存感知调度思想呼应 [P13]。
- P06的Llumnix通过跨实例KV缓存迁移实现负载均衡，扩展了KV缓存管理的分布式维度 [P06]。
- P27的QLM专注于SLO队列管理，可与OrbitFlow等SLO感知的KV管理方法结合 [P27]。

#### 分类趋势

- 从固定连续分配到分页、虚拟内存、token级虚拟化，粒度不断细化以消除碎片 [P01] [P03] [P24]。
- 存储层级从GPU扩展到CPU、SSD、CXL共享内存，形成多级缓存体系 [P11] [P17] [P18] [P19] [P23]。
- 有损压缩被引入以提升容量和带宽利用率，并逐步发展为联合优化与无损验证 [P20] [P21] [P22]。
- 缓存管理逐渐与请求调度、SLO保障深度融合，形成协同优化 [P02] [P09] [P13] [P23]。
- 针对长上下文和RAG等场景的专用KV复用策略不断涌现 [P09] [P19] [P23]。

### 并行计算与分布式执行

本类别聚焦于并行计算与分布式执行技术在大语言模型推理系统中的应用，核心挑战包括张量并行中的非确定性、资源利用效率与训练-推理一致性 [P31]。

主分类论文：[P31]

#### 技术演进主线：确定性张量并行推理

**主线问题：** 如何消除不同张量并行大小导致的非确定性，实现训练与推理的概率匹配？

不同张量并行大小会引入浮点运算顺序差异，导致同一输入在不同 TP 配置下产生不同的推理结果，进而造成训练与推理之间的概率失配，影响强化学习等场景的稳定性和可复现性 [P31]。

##### 1. [P31] Deterministic Inference across Tensor Parallel Sizes That Eliminates Training-Inference Mismatch

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：张量并行大小的变化导致浮点归约顺序不一致，使得推理结果非确定，且训练和推理的概率分布不匹配。
- 本作贡献或改进：提出 Tree-Based Invariant Kernels (TBIK)，通过固定二叉树归约顺序统一 GPU 内 MatMul 与 GPU 间 All-Reduce，实现跨张量并行大小的逐位确定性推理，并集成到 vLLM 和 FSDP 中消除 RL 管线的概率失配。
- 代价与权衡：确定性推理带来显著延迟开销，端到端 22%–63%；Tree-Based MatMul 在小 M 时吞吐低于 cuBLAS。
- 剩余问题：当前实现尚未达到生产级性能，且未支持量化数据类型。
- 关系依据：该工作 [P31] 提出了 Tree-Based Invariant Kernels (TBIK)，通过固定二叉树归约顺序统一 GPU 内 MatMul 与 GPU 间 All-Reduce，实现跨张量并行大小的逐位确定性推理，并解决 RL 管线中 vLLM 与 FSDP 的概率失配问题。作为首个系统性消除 TP 非确定性的方案，本步骤为后续研究奠定了基础。

#### 分类趋势

- 从通用张量并行优化转向针对特定应用（如强化学习）的确定性执行保证，以解决训练-推理不一致问题 [P31]。
- 确定性推理的实现依赖于软硬件协同设计，包括定制内核与通信原语的联合优化 [P31]。

### 训练系统与优化

本类目聚焦大语言模型服务中的训练系统与优化，尤其关注在不增加硬件资源的前提下，将空闲推理容量转化为微调吞吐的协同服务设计。核心论文 DeltaServe [P32] 提出主机无关的推理与微调协同方案，通过 SLO 感知调度、CUDA-graph 感知延迟模型及独立反向子进程，在保持推理延迟目标的同时提升 LoRA 微调吞吐。

主分类论文：[P32]

#### 技术演进主线：推理与微调协同服务

**主线问题：** 如何在不增加硬件的前提下，利用空闲推理容量进行 LoRA 微调，同时保持推理 SLO 合规？

该线程围绕推理与微调的协同服务展开。DeltaServe [P32] 作为基础工作，将空闲推理 GPU 容量转化为 LoRA 微调吞吐，通过 SLO 感知准入调度、CUDA-graph 感知延迟模型和独立反向子进程，在主流推理引擎上实现 SLO 合规下的微调吞吐提升。

##### 1. [P32] DeltaServe: Host-Agnostic Co-Serving of Inference and Fine-Tuning for LLMs

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：现有方法通常需要额外专用 GPU 进行微调，或牺牲推理 SLO 来换取微调吞吐，导致资源利用率低或服务质量下降。
- 本作贡献或改进：DeltaServe [P32] 提出主机无关的协同服务设计，将空闲推理容量转化为 LoRA 微调吞吐。其核心创新包括：SLO-aware 微调准入调度，利用 LoRA 前向与推理 prefill 的结构一致性将微调作为 prefill-only 请求并入推理 batch；CUDA-graph-aware 延迟模型离线校准、在线精修以区分 graph 与 eager 执行模式的延迟差异；以及解耦反向执行器在独立 GPU 子进程中进行反向传播和优化器更新，支持抢占。
- 代价与权衡：需要宿主引擎支持 multi-LoRA batching；混合 batch 因激活捕获 hooks 无法在回放的 CUDA graph 内运行而被迫使用 eager 执行，可能损失 CUDA graph 回放优势；反向子进程在 prefill 请求到达时会被抢占，突发推理负载下微调吞吐会明显下降。
- 剩余问题：缺少对其他模型架构、更大模型或不同类型数据集上的行为评估；未解决混合 batch 中 CUDA graph 回放无法使用的问题；突发负载下微调吞吐下降问题有待优化。
- 关系依据：P32 是本文线程的起始工作，提出 DeltaServe 这一主机无关的协同服务设计，将空闲推理 GPU 容量转化为 LoRA 微调吞吐 [P32]。

#### 横向与跨主线联系

- P01 提出 PagedAttention 内存管理，可支持 multi-LoRA batching，为 DeltaServe [P32] 的宿主引擎集成提供基础。
- P02 中 SGLang 作为 DeltaServe [P32] 验证的宿主引擎之一，其 RadixAttention 缓存复用可能影响协同服务时的 KV cache 行为。
- P27 的队列管理同样关注 SLO 达成率，与 DeltaServe [P32] 的 SLO-aware 调度思路相关，但前者面向通用推理队列，后者针对微调与推理协同场景。

#### 分类趋势

- 推理与微调协同服务成为提高 GPU 利用率、降低微调成本的新趋势，通过复用空闲推理容量避免额外硬件投入 [P32]。
- SLO 感知调度在协同服务中愈发重要，将推理延迟预算动态分配给微调任务，以保障服务质量 [P32]。
- 硬件与软件协同设计，如 CUDA-graph 感知延迟模型和独立反向子进程，用于优化混合工作负载的执行效率 [P32]。

### 模型压缩与低精度计算

本类别涵盖KV Cache量化、注意力内核低精度化以及面向LLM推理的模型压缩技术。P07提出2bit非对称KV Cache量化方法，显著降低内存占用并提升吞吐 [P07]；P08将INT8量化与FlashAttention结合，加速注意力计算 [P08]；P10通过编码压缩KV Cache传输，降低网络延迟 [P10]；P25在2bit量化基础上引入逐层金字塔预算分配，进一步压缩KV Cache [P25]；P26提出在线-离线混合量化，结合硬件协同设计提升推理效率 [P26]。这些工作共同推动LLM推理中低精度计算与模型压缩的发展。

主分类论文：[P07], [P08], [P10], [P25], [P26]

#### 技术演进主线：KV Cache低精度量化与内存优化

**主线问题：** 如何通过低精度KV Cache量化与调度策略在保持模型质量的同时提升LLM推理效率？

本线程以KV Cache量化为主线，从P07的基础2bit非对称量化方法出发 [P07]，P10提出正交的编码压缩与流式传输优化 [P10]，P25在P07基础上进行直接改进，引入逐层金字塔预算分配与两遍注意力内核 [P25]，P26进一步扩展机制，提出在线-离线混合量化与硬件协同设计 [P26]。

##### 1. [P07] KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：KV Cache占用大量GPU内存，限制LLM推理的batch size和吞吐。
- 本作贡献或改进：提出KIVI，一种无需微调的2bit非对称量化方法，按通道量化key cache、按token量化value cache，显著降低KV Cache内存占用。
- 代价与权衡：对multi-query attention模型（如Falcon-7B）2bit量化可能导致较大精度下降，需要4bit量化；在困难生成任务上依赖全精度滑动窗口。
- 剩余问题：吞吐提升还可通过将KV Cache量化过程与前序算子融合进一步增大，该优化留作未来工作。
- 关系依据：P07作为KV Cache量化领域的基础工作，首次提出无微调的2bit非对称量化方法，为后续研究提供算法基础和性能基准 [P07]。

##### 2. [P10] CacheGen: KV Cache Compression and Streaming for Fast Large Language Model Serving

- 关系类型：正交工作
- 承接论文：[P07]
- 前作问题：KV Cache传输带宽高，导致LLM服务的TTFT较大，在带宽受限环境下尤为严重。
- 本作贡献或改进：提出CacheGen，利用KV Cache分布特性进行delta编码、分层量化和算术编码，压缩为bitstream并流式传输，自适应带宽调整压缩级别。
- 代价与权衡：未在超大模型上评估；网络模型未包含极高带宽条件；真实场景上下文复用缺乏公开数据集支撑。
- 剩余问题：需要进一步在超大模型和复杂网络条件下验证，并集成更多真实工作负载。
- 关系依据：P10关注KV Cache的编码压缩与流式传输优化，目标在于降低网络带宽和TTFT，与P07的量化方案在目标、方法和应用场景上不同，属于并行优化路径，二者可互补但无直接改进关系 [P07] [P10]。

##### 3. [P25] MiniKV: Pushing the Limits of LLM Inference via 2-Bit Layer-Discriminative KV Cache

- 关系类型：直接改进
- 承接论文：[P07]
- 前作问题：P07的2bit量化方法未考虑层间差异，KV Cache预算分配均匀，长上下文任务中准确率可能下降。
- 本作贡献或改进：提出MiniKV，在2bit量化基础上引入金字塔逐层KV预算分配，设计兼容FlashAttention的两遍注意力内核，实现更高准确率和更长序列支持。
- 代价与权衡：尝试组合SnapKV与KIVI时准确率下降，需要更鲁棒的组合框架；尚未与模型压缩等其他优化技术组合。
- 剩余问题：需要探索更鲁棒的KV淘汰与量化组合方法，并与其他模型压缩技术集成。
- 关系依据：P25在P07的2bit量化基础上引入逐层金字塔KV预算分配，并设计兼容FlashAttention的两遍注意力内核，在相同KV Cache大小下达到更高准确率，是对P07量化方法的直接改进和系统级拓展 [P07] [P25]。

##### 4. [P26] Oaken: Fast and Efficient LLM Serving with Online-Offline Hybrid KV Cache Quantization

- 关系类型：机制扩展
- 承接论文：[P07], [P25]
- 前作问题：现有KV Cache量化方法（如P07、P25）需要在线进行异常值检测或复杂量化，增加在线推理开销。
- 本作贡献或改进：提出Oaken，在线-离线混合量化算法，离线确定异常值阈值，在线仅计算量化scale，结合group-shift量化与融合编码，降低位宽并提升吞吐。
- 代价与权衡：当总序列长度低于8K时，GPU上的其他方案可能超过Oaken；对grouped-query attention模型，KV Cache较小，性能增益有限。
- 剩余问题：需要进一步优化短序列场景下的性能，并扩展到更多模型架构。
- 关系依据：P26提出在线-离线混合量化，通过离线确定异常值阈值避免在线高开销检测，结合group-shift量化与融合编码进一步降低位宽，继承P07的量化思想和P25的KV缓存优化目标，但引入新的机制（离线阈值、硬件协同），属于机制扩展 [P07] [P25] [P26]。

#### 技术演进主线：注意力内核的低精度量化

**主线问题：** 如何将INT8量化与FlashAttention内核高效结合以提升注意力计算速度？

本线程以注意力算子的低精度优化为核心，P08作为基础工作，提出首个与FlashAttention兼容的INT8量化架构 [P08]。

##### 1. [P08] INT-FlashAttention: Enabling Flash Attention for INT8 Quantization

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：注意力计算在LLM推理中占用大量时间，FlashAttention虽优化了内存访问，但计算仍为FP16/FP8，速度提升有限。
- 本作贡献或改进：提出INT-FlashAttention，首个与FlashAttention前向流程兼容的token-level INT8量化架构，用INT8 GEMM替换所有矩阵乘法，显著提升推理速度并降低量化误差。
- 代价与权衡：V矩阵仅实现tensor-level量化，尚未实现per-token量化；未来需per-block量化和Hadamard变换进一步优化。
- 剩余问题：需要实现per-token/per-block量化V矩阵，并探索与变换结合以进一步提升速度和精度。
- 关系依据：P08作为该线程的基础工作，提出首个与FlashAttention前向流程兼容的token级INT8量化架构，用INT8 GEMM替换所有矩阵乘法，在Ampere GPU上显著提升推理速度并降低量化误差，为注意力算子的低精度优化奠定基础 [P08]。

#### 横向与跨主线联系

- KV Cache量化工作（P07、P25、P26）可与vLLM的PagedAttention内存管理技术结合，进一步降低显存占用并提升吞吐 [P01]。
- CacheGen的KV Cache流式压缩方法可与vLLM等推理服务系统集成，降低TTFT [P10]。
- MiniKV的自定义注意力内核与vLLM的PagedAttention内核优化方向一致，可相互借鉴 [P03]。
- Oaken的硬件协同设计思路与Tutti的SSD-backed KV Cache存储优化可互补，共同提升长上下文推理效率 [P17]。

#### 分类趋势

- KV Cache量化从基础2bit非对称方法向逐层自适应预算分配和在线-离线混合量化演进，压缩率不断提高且精度损失可控 [P07] [P25] [P26]。
- 低精度计算从KV Cache扩展至注意力内核，INT8量化与FlashAttention结合实现端到端加速 [P08]。
- KV Cache优化不仅关注单卡内存，还扩展到网络传输和异构存储，通过编码压缩和硬件协同设计提升系统整体效率 [P10] [P26]。
- 量化方法逐渐与系统级调度、内存管理技术融合，形成软硬件一体的LLM推理优化方案 [P25] [P26]。

### 性能评测与成本分析

本类别聚焦于对 LLM 服务系统进行系统性的性能、能耗与成本评估，以及真实工作负载的刻画与生成。P04 发布了首个大规模真实世界 LLM 服务数据集 BurstGPT [P04]，为后续研究提供了真实负载依据。P28 对生产环境多模态与推理模型工作负载进行了深入刻画，并提出了 ServeGen 生成框架 [P28]。P29 则针对 vLLM 推理引擎的配置空间进行了全面的能耗、性能与准确率权衡评估 [P29]。

主分类论文：[P04], [P28], [P29]

#### 技术演进主线：LLM 服务性能评测与成本分析

**主线问题：** 如何系统评估和优化 LLM 服务系统的性能、能耗与成本，并确保评测负载和配置空间反映真实生产环境？

该线程从真实工作负载数据集的构建出发，逐步扩展到多模态与推理模型负载的生成，最终深入到推理引擎配置空间的系统评测。P04 提供了 BurstGPT 数据集，揭示了突发性、短对话和高失败率等真实特征 [P04]。P28 在此基础上进一步覆盖多模态和推理模型，提出 ServeGen 框架 [P28]。P29 则转向 vLLM 配置的能耗与性能权衡，为配置优化提供实证依据 [P29]。

##### 1. [P04] BurstGPT: A Real-World Workload Dataset to Optimize LLM Serving Systems

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：缺乏大规模真实世界 LLM 服务工作负载数据集，导致系统评估使用合成负载而偏离实际。
- 本作贡献或改进：发布了 BurstGPT 数据集和基准套件，刻画了用户并发突发性、对话模式、响应长度和失败特征。
- 代价与权衡：数据集仅来自单一提供商，可能不完全代表所有部署形态；对 Llama-2 的对比使用非真实对话提示。
- 剩余问题：未覆盖多模态和推理模型工作负载，需要进一步扩展负载类型和部署多样性。
- 关系依据：P04 作为线程基础，提供了首个大规模真实工作负载数据集 [P04] [P04] [P04] [P04]

##### 2. [P28] ServeGen: Workload Characterization and Generation of Large Language Model Serving in Production

- 关系类型：机制扩展
- 承接论文：[P04]
- 前作问题：P04 的数据集主要覆盖语言模型，未涵盖多模态和推理模型的工作负载特征。
- 本作贡献或改进：扩展了工作负载特征刻画范围，并提出按客户端生成的 ServeGen 框架，更真实地模拟生产负载。
- 代价与权衡：未覆盖插件调用和前缀缓存分析；单个工作负载时间跨度有限。
- 剩余问题：尚未将生成的工作负载用于系统性能与能耗的评测。
- 关系依据：P28 在 P04 的基础上扩展了负载类型和生成机制 [P04] [P28] [P04] [P28]

##### 3. [P29] Attention to Detail: Evaluating Energy, Performance, and Accuracy Trade-offs Across vLLM Configurations

- 关系类型：评测与验证
- 承接论文：[P04], [P28]
- 前作问题：缺乏对 vLLM 配置空间（注意力内核、前缀缓存、分块预填）的能耗、性能与准确率权衡的系统性评测。
- 本作贡献或改进：通过 9000 次受控运行揭示了配置间交互效应和任务相关性，并发现配置可能影响准确率。
- 代价与权衡：仅使用单一 GPU 和有限配置选项，硬件和负载覆盖有限；能耗测量存在误差。
- 剩余问题：评测结果尚未扩展到其他推理引擎、硬件平台和更广泛的配置空间。
- 关系依据：P29 利用 P04 和 P28 提供的真实负载认知，对配置空间进行系统评测 [P04] [P28] [P29] [P04] [P28] [P29]

#### 横向与跨主线联系

- P01 提出的 PagedAttention 通过 KV cache 分页管理显著提升内存利用率和吞吐，与 P29 评测的前缀缓存和分块预填配置密切相关 [P01] [P29]
- P02 的 SGLang 采用 RadixAttention 实现 KV 缓存复用，与 P29 评测的前缀缓存效果互为补充 [P02] [P29]
- P03 的 vAttention 通过虚拟内存管理动态分配 KV cache，可作为 P29 配置优化的替代方案 [P03] [P29]
- P07 的 KIVI 通过 2bit 量化压缩 KV cache，与 P29 的能耗优化目标一致 [P07] [P29]
- P06 的 Llumnix 通过动态调度提升服务效率，与 P04 和 P28 的负载特征研究相关 [P06] [P04] [P28]

#### 分类趋势

- 从真实负载数据集的构建向更全面的负载生成与配置评测演进 [P04] [P28]
- 评估视角从单一的吞吐和延迟扩展到能耗、准确率等多维度权衡 [P29]
- 评测方法日益系统化，强调配置间交互和任务类型的影响 [P29]

### 可靠性、弹性与可观测性

本类别关注 LLM 推理服务在并发请求下的可靠性挑战，涵盖 KV 缓存隔离失效、跨请求性能干扰与崩溃/存活问题。P30 提出的 GRIEF 通过灰盒模糊测试系统性地发现此类服务层漏洞，将并发请求轨迹作为测试输入，验证了内存管理（KV cache）与请求调度（并发批处理、适配器调度、前缀共享）的工程决策会引入安全与可靠性风险 [P30]。

主分类论文：[P30]

#### 技术演进主线：LLM 推理服务可靠性模糊测试

**主线问题：** 如何系统性地发现 LLM 推理服务中的可靠性漏洞？

该线程以 GRIEF 为起点，为 LLM 推理服务建立了面向并发请求轨迹的灰盒模糊测试范式。此前工作主要集中在性能优化或单请求正确性，而并发负载下的服务层缺陷（如 KV 缓存污染、调度饥饿、延迟崩溃）缺少系统化测试方法 [P30]。

##### 1. [P30] Continuous Discovery of Vulnerabilities in LLM Serving Systems with Fuzzing

- 关系类型：基础工作
- 承接论文：无（本主线起点）
- 前作问题：LLM 推理服务中存在由并发请求交互引发的可靠性漏洞，如 KV 缓存隔离失效、跨请求性能干扰和崩溃/存活问题，但缺乏专门针对此类服务层缺陷的测试工具，现有模糊测试方法未考虑多请求时间轨迹与共享状态竞争。
- 本作贡献或改进：GRIEF 提出了一种面向 LLM 推理引擎的灰盒模糊测试工具，以带时间戳的多请求轨迹为输入，通过时序、事件、拼接变异及定向拼接生成测试用例，并设计行为、结构与关系预言机及受控重放确认管线，在 vLLM 和 SGLang 中发现 15 个潜在漏洞（10 个开发者确认，含 2 个 CVE）。
- 代价与权衡：当前评估限于 vLLM 和 SGLang 及代表性服务模式与硬件，扩展到其他引擎或部署需要额外适配器与遥测钩子；GRIEF 不能证明无 bug，效果受种子、变异、反馈和模糊测试预算影响；最强结构预言机依赖引擎级可观测性，确认策略保守可能漏报低置信度候选。
- 剩余问题：尚未覆盖分布式部署、异构硬件后端和不同模型架构；无法保证完备性；对低置信度漏洞可能漏报；漏洞的实际可利用性取决于具体生产环境的租户隔离、批处理策略、限流、监控和恢复机制，仍需进一步评估。
- 关系依据：P30 作为该线程的首个也是基础工作，提出了 GRIEF 工具并验证了其在 LLM 推理服务可靠性模糊测试中的有效性 [P30]。

#### 横向与跨主线联系

- P01 提出的 PagedAttention 通过分页管理 KV 缓存降低内存浪费，而 P30 发现 KV 缓存隔离缺陷可导致跨请求输出污染，两者分别从性能和可靠性角度关注 KV 缓存管理 [P01][P30]。
- P02 的 SGLang 采用 RadixAttention 进行 KV 缓存复用，但 P30 在 SGLang 中发现 LoRA 调度器崩溃，表明高效缓存与调度设计可能引入新的可靠性风险 [P02][P30]。
- P29 系统评估了 vLLM 配置对能耗、延迟和准确率的权衡，而 P30 揭示 vLLM 在并发负载下的服务层漏洞，两者共同强调推理服务配置与实现的可靠性影响 [P29][P30]。

#### 分类趋势

- 从单请求性能优化转向并发负载下的可靠性与安全测试 [P30]。
- 将模糊测试思想扩展到推理服务，以时间轨迹捕捉共享状态竞争 [P30]。
- 强调服务层缺陷的静默性与延迟性（如 KV 污染、性能饥饿、延迟崩溃），需要专门预言机与取证方法 [P30]。

## 跨论文发现

- PagedAttention 通过分页式 KV 缓存管理几乎消除了内部和外部碎片，成为 vLLM 及众多调度系统的内存管理基石，并支持了高效的跨请求复用与共享 [P01]。
- KV 缓存管理从固定连续分配演进到分页、虚拟内存、token 级虚拟化，粒度不断细化以回收任何层级的内存浪费 [P01] [P03] [P24]。
- 多级存储层次（GPU、CPU、SSD、CXL 共享内存）被广泛采用以扩展 KV 缓存容量，并需要配套的 I/O 优化和缓存感知调度来隐藏数据移动延迟 [P11] [P17] [P18] [P19] [P23]。
- KV 缓存有损压缩通过量化或编码技术显著降低内存占用和传输带宽，但需要联合优化或验证机制来维持模型质量 [P07] [P10] [P20] [P21] [P22] [P25] [P26]。
- 请求调度从单机内的 nano-batch 流水线和 intra-device 并行逐步演进到跨实例的动态请求迁移与全局队列管理，调度粒度不断细化至任意 token 边界 [P05] [P06] [P14] [P27]。
- prefill/decode 解耦是降低延迟的关键技术路径，从跨实例分离式执行发展到单 GPU 内动态 SM 分区，同时保持高吞吐 [P06] [P15]。
- SLO 感知和公平性成为调度策略的核心目标，系统通过动态优先级、赤字机制和局部性感知来兼顾吞吐与服务质量 [P12] [P13] [P16] [P27] [P32]。
- 低精度计算从 KV 缓存量化扩展到注意力内核，INT8/2bit 量化与 FlashAttention 等高效算子结合，实现端到端加速 [P07] [P08] [P25] [P26]。
- 真实工作负载刻画显示出强烈的突发性和异构性，驱动了动态调度和弹性资源管理的研究 [P04] [P06] [P28]。
- 推理服务中的并发请求交互可能引发 KV 缓存污染、调度饥饿和延迟崩溃等可靠性问题，需要专门的灰盒模糊测试来系统发现 [P30]。

## 技术比较

- 在 GPU 内存管理上，PagedAttention 采用块表间接寻址，而 vAttention 通过虚拟内存保留连续地址空间，避免了内核重写，形成替代技术路线 [P01] [P03]，vToken 则在块管理之上增加 token 级间接寻址，进一步回收块内碎片，扩展了 PagedAttention 的能力 [P24]。
- 跨实例调度中，Llumnix 依赖 KV cache 迁移实现负载均衡，而 QLM 通过请求等待时间估计和全局队列管理避免迁移开销，两者为实现 SLO 达成提供了不同取舍 [P06] [P27]。
- KV 缓存压缩方面，AdaptCache 采用固定压缩策略与独立设备放置，而 EVICPRESS 通过统一效用函数联合优化压缩与驱逐决策，直接改进了压缩质量与延迟的权衡 [P20] [P21]，VeriCache 则通过有损压缩加验证机制保证无损输出，属于机制扩展 [P22]。
- KV 缓存量化中，KIVI 提出基础 2bit 非对称量化，MiniKV 通过逐层金字塔预算分配提升长上下文准确率，是对前者的直接改进 [P07] [P25]；Oaken 引入离线阈值确定与硬件协同编码，属于机制扩展 [P26]；CacheGen 则专注于编码压缩与流式传输，与量化方法正交 [P10]。
- 调度粒度上，NanoFlow 使用 nano-batch 重叠资源操作 [P05]，DynaServe 引入 micro-request 在任意 token 边界切分，极大细化了跨实例调度单元，并统一了共置与分离式执行 [P14]。
- 张量并行确定性上，TBIK 通过固定二叉树归约顺序实现跨 TP 大小的逐位确定性，与多数推理系统的非确定性浮点累积形成对比 [P31]。
- 在推理与微调协同上，DeltaServe 利用 SLO 感知调度和独立反向子进程复用空闲推理容量，与传统专用 GPU 微调相比显著提高了资源利用率 [P32]。

## 研究空白

- 大规模集群和超长上下文场景下的动态调度与请求切分方法缺乏验证，DynaServe 和 OrbitFlow 等系统在分布式、多节点以及极端 SLO 压力下的表现尚待研究 [P14] [P23]。
- 注意力内核的低精度量化仍不完善，INT-FlashAttention 尚未实现对 V 矩阵的 per-token 或 per-block 量化，也未探索 Hadamard 变换等进一步优化 [P08]。
- KV 缓存有损压缩与量化在大规模部署中的鲁棒性和泛化能力不足，现有方法多在小模型或单节点验证，且组合不同压缩技术时可能出现准确率下降 [P20] [P21] [P25]。
- 张量并行确定性推理的延迟开销高达 22%–63%，且未支持量化数据类型，距离生产级性能仍有显著差距 [P31]。
- 混合负载下的推理与微调协同服务仍面临 CUDA graph 回放限制和突发负载抢占导致微调吞吐骤降的问题，需要进一步优化 [P32]。
- 可靠性模糊测试目前仅覆盖 vLLM 和 SGLang 及单节点部署，对分布式、异构硬件和多模型架构的覆盖不足，且无法保证完备性 [P30]。
- 真实工作负载数据集主要来源于单一提供商或有限时间跨度，难以全面反映多模态、插件调用及长期生产环境的变化 [P04] [P28]。
- vLLM 配置空间的能耗与性能评测局限于单 GPU 和少量配置项，缺乏对其他推理引擎、硬件平台及更大配置空间的全面分析 [P29]。

## 结论

本综述梳理了 AI Infra Systems 在内存管理、调度、并行执行、低精度计算和可靠性方面的关键技术演进，揭示了从单体优化到系统级协同设计的总体趋势。PagedAttention 开启的分页内存管理成为调度与共享的基础，多级存储和压缩技术不断扩展 KV 缓存的容量与效率，动态调度和 SLO 感知从单机延伸到跨实例并细化至微请求粒度，低精度计算与软硬件协同持续压缩推理成本。然而，现有研究在分布式确定性、超长上下文效率、压缩鲁棒性、实测负载覆盖和可靠性保障等方面仍存在显著空白。未来工作应加强跨层协同、引入更精细的运行时反馈机制，并在真实部署环境中验证系统优化，以满足日益增长的大模型推理需求。

## 逐篇阅读卡片

### P01 · Efficient Memory Management for Large Language Model Serving with PagedAttention

vLLM 提出 PagedAttention，将 KV cache 划分为由块表映射的非连续物理块，按需分配并支持请求内/跨请求共享，从而几乎消除 KV cache 内存浪费，较 FasterTransformer 和 Orca 获得 2–4× 的吞吐提升。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 并行计算与分布式执行, 异构硬件与内核优化, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行与软硬件协同提高大模型在线推理的吞吐与内存效率？本文具体回答：操作系统式分页如何映射到 KV cache 的分配、共享和近零浪费。
- 方法：作者指出现有系统以连续张量预分配 KV cache 导致内部碎片、外部碎片且无法共享；借鉴 OS 虚拟内存分页，提出 PagedAttention 算法，将 KV cache 分成固定大小的逻辑块并映射到非连续物理块。在此基础上实现 vLLM，包含集中式调度器、GPU/CPU 块分配器、块表、copy-on-write、抢占（交换/重计算）、Megatron-LM 风格张量模型并行，以及融合 reshape/block write/attention/block copy 的定制 CUDA kernel。
- 实验设置：使用 OPT-13B/66B/175B 与 LLaMA-13B 模型，运行在 Google Cloud A2 实例的 NVIDIA A100 GPU 上（13B 为单 A100 40GB，66B 为 4×A100，175B 为 8×A100-80GB）；工作负载基于 ShareGPT 和 Alpaca 数据集的输入/输出长度并以 Poisson 过程生成请求到达，基线为 FasterTransformer 和三种 Orca 变体（Max/Pow2/Oracle）；主要指标是归一化延迟（每请求端到端延迟除以输出长度）；大多数实验使用 1 小时轨迹，OPT-175B 使用 15 分钟轨迹，并包含 kernel 微基准、block size 消融以及 recompute/swap 对比。
- 与综述主题的关系：论文直接面向 AI Infra 中的 KV Cache 与内存管理瓶颈：用 OS 式分页把缓存分配从连续大块变为固定大小物理块，并通过块表、copy-on-write、请求调度/抢占、分布式张量并行和定制 CUDA kernel 的协同设计，提高在线推理吞吐和内存效率；论文不涉及训练系统、模型压缩或低精度计算。
- 置信度：0.95

主要贡献：

- 识别 LLM serving 中 KV cache 内存分配的挑战并量化其对 serving 性能的影响。
- 提出 PagedAttention，一种在非连续分页内存上运行的注意力算法，灵感来自 OS 的虚拟内存和分页。
- 设计并实现 vLLM，一个基于 PagedAttention 的分布式 LLM serving 引擎。
- 在多种场景下评估 vLLM，显示其显著优于 FasterTransformer 和 Orca 等先前最先进系统。

局限：

- PagedAttention 的块映射使 attention kernel 延迟比 FasterTransformer 高 20–26%，带来额外开销。
- 虚拟内存/分页技术并非普遍适用于所有 GPU 工作负载；对计算密集型或张量形状静态的负载，内存效率提升可能不转化为性能提升，反而因内存间接寻址和非连续块内存而性能下降。
- 在 OPT-175B + Alpaca 这种内存充足且序列短的配置下，vLLM 相对 Orca (Oracle/Pow2) 的优势变小，因为系统变为 compute-bound。

证据：

- PagedAttention 借鉴操作系统虚拟内存与分页技术，使 vLLM 在 KV cache 内存上实现近零浪费，并支持请求内及跨请求的 KV cache 灵活共享。 — “To address this problem, we propose PagedAttention, an attention algorithm inspired by the classical virtual memory and paging techniques in operating systems. On top of it, we build vLLM, an LLM serving system that achieves (1) near-zero waste in KV cache memory and (2) flexible sharing of KV cache within and across requests to further reduce memory usage.”，p. 1
- PagedAttention 通过将 KV cache 划分为固定大小、无需连续存放的块，按需分配小块以缓解内部碎片，统一块大小消除外部碎片，并实现块粒度的内存共享。 — “This design alleviates internal fragmentation by using relatively small blocks and allocating them on demand. Moreover, it eliminates external fragmentation as all blocks have the same size. Finally, it enables memory sharing at the granularity of a block, across the different sequences associated with the same request or even across the different requests.”，p. 2

### P02 · SGLang: Efficient Execution of Structured Language Model Programs

SGLang 通过前端结构化生成语言与后端运行时协同，提出 RadixAttention 的 radix-tree LRU KV 缓存复用、压缩有限状态机快速约束解码和 API 推测执行，在多种 LLM/多模态工作负载上显著提升吞吐并降低延迟。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？本文聚焦其中结构化多调用 LLM 程序的高效执行。
- 方法：论文提出 SGLang 系统，分为 Python 嵌入式 DSL 前端和 SGLang Runtime 后端。前端提供 extend/gen/select/fork/join/image/video 等原语和流式解释器；后端实现了 RadixAttention（用 radix tree 管理 KV cache 的 LRU 缓存与缓存感知调度）、压缩有限状态机（将 FSM 中连续单值转移边合并为可一次解码多 token 的压缩边）以及 API speculative execution（对黑盒 API 模型推测式继续生成以复用结果）。
- 实验设置：实验使用 Llama-2-7B/70B、Mixtral-8x7B、LLaVA-v1.5-7B（图像）、LLaVA-NeXT-34B（视频）和 OpenAI GPT-3.5，硬件为 AWS EC2 G5（NVIDIA A10G 24GB）与 A100G 80GB；7B 模型单卡，更大模型使用张量并行；对比基线包括 Guidance、vLLM、LMQL 和多模态任务中作者原实现。工作负载涵盖 MMLU、HellaSwag、ReAct agent、generative agents、Tree-of-thought、Skeleton-of-thought、LLM judge、JSON decoding、多轮对话、DSPy RAG pipeline 和多模态评测。
- 与综述主题的关系：该论文是 AI Infra Systems 中 KV Cache 与内存管理、推理服务与请求调度方向的重要工作：RadixAttention 将 KV cache 视为 radix tree 上的 LRU 缓存，在前缀共享、fork/join 并行等复杂多调用程序结构中自动复用缓存，减少冗余 prefill 并提升批处理吞吐；压缩 FSM 则通过解码多 token 降低结构化输出延迟，与 vLLM 等系统的调度与内存优化互补。
- 置信度：0.95

主要贡献：

- 提出 SGLang 前端语言，以 Python 嵌入式 DSL 提供 extend/gen/select/fork/join/image/video 等原语，简化多调用 LM 程序的编程。
- 提出 RadixAttention：将 KV cache 组织为 radix tree 的 LRU 缓存，支持自动前缀复用、缓存感知调度和分布式扩展。
- 提出压缩有限状态机（Compressed FSM），将正则约束下可合并的多 token 路径一次解码，加速结构化输出生成。
- 提出 API speculative execution，针对黑盒 API 模型减少多调用程序的延迟和输入 token 成本。
- 在多种模型与工作负载上验证最高 6.4× 吞吐提升和 3.7× 延迟降低。

局限：

- 编译器模式目前只支持无数据依赖控制流的程序，数据依赖控制流留待未来工作。
- 缓存感知调度可能导致饥饿，与公平调度方法的集成留作未来工作。
- 压缩 FSM 可能因字符串与 token 之间的差距产生扭曲概率，论文仅提出缓解方向而未完全解决。
- API speculative execution 依赖模型能高精度匹配模板，否则准确性无法保证。

证据：

- RadixAttention 的核心机制是不再在请求结束后丢弃 KV cache，而是将其保留在 radix tree 中，从而支持前缀搜索、复用、插入和淘汰。 — “Unlike existing systems that discard the KV cache after a generation request finishes, our system retains the cache for prompts and generation results in a radix tree, enabling efficient prefix search, reuse, insertion, and eviction.”，p. 4
- SGLang 将 KV cache 作为传统缓存管理，并用 radix tree 实现高效匹配、插入和淘汰，运行时能够通过缓存感知调度策略处理各种复用模式。 — “This approach manages the KV cache as a traditional cache and uses a radix tree for efficient matching, insertion, and eviction. It allows the runtime to handle various reuse patterns with a cache-aware scheduling policy efficiently.”，p. 2

### P03 · vAttention: Dynamic Memory Management for Serving LLMs without PagedAttention

vAttention 通过 CUDA 虚拟内存管理 API 解耦虚拟与物理内存分配，在保留 KV cache 虚拟连续性的同时按需映射物理页，避免了 PagedAttention 对注意力内核重写和块表维护的需求，从而提升 LLM 推理吞吐与内核可移植性。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 异构硬件与内核优化, 性能评测与成本分析
- 研究问题：如何在不采用 PagedAttention 所要求的非连续虚拟内存布局的前提下，通过解耦虚拟与物理内存分配实现 KV cache 的动态内存管理，并提升注意力内核的兼容性、简化编程以及提高 LLM 服务吞吐？
- 方法：论文分析了 PagedAttention 因动态分配导致 KV cache 虚拟内存非连续而带来的内核重写、冗余内存管理和运行时开销问题，提出 vAttention：利用 CUDA VMM API 预先预留连续虚拟内存、运行时按需映射物理页面，并通过后台线程重叠内存分配与计算、延迟回收与提前映射、修改开源 NVIDIA 驱动以支持 64KB 小页等优化来隐藏分配延迟、降低内部碎片；作者将 vAttention 集成到 vLLM 中，接入未修改的 FlashAttention-2、FlashInfer 和 FlashAttention-3 内核进行评估。
- 实验设置：评估使用 Yi-6B（1 张 A100）、Llama-3-8B 和 Yi-34B（各 2 张 NVLink 连接的 A100），并以 1-2 张 H100 演示 FlashAttention-3 的可移植性；以 vLLM v0.2.7 为统一 serving 框架，集成 FlashAttention-2 v2.5.9 与 FlashInfer v0.4.0 的 paged 和非 paged 内核；工作负载包括 arXiv-Summarization 长上下文离线/在线 trace 和 OpenChat 动态 trace；基线和配置包括 FA2_Paged、FI_Paged、vLLM 原生 decode kernel 以及 vAttention 支持的非 paged 内核。
- 与综述主题的关系：该论文直接回应 AI Infra Systems 中的 KV Cache 与内存管理问题：它指出 PagedAttention 以非连续虚拟内存换取物理内存动态分配会带来内核重写、冗余管理和性能开销，并提出基于虚拟/物理内存解耦的 vAttention，使动态内存分配对注意力内核透明，从而在提升吞吐的同时增强内核可移植性；这与推理服务中的请求调度、低精度/新内核快速接入以及成本效率密切相关。
- 置信度：0.95

主要贡献：

- 提出 vAttention：一种保留 KV cache 虚拟连续性的动态内存管理方法，借助 CUDA VMM API 解耦虚拟与物理内存分配，同时按需提交物理内存。
- 使 vLLM 能够无需修改内核即可支持 FlashAttention-2、FlashInfer 以及 FlashAttention-3 等注意力后端，展示了对新型 Hopper 内核的开箱即用可移植性。
- 引入多项 LLM 特定优化：内存分配与计算重叠、延迟回收与提前分配、以及通过修改开源 NVIDIA 驱动支持 64KB 小页以缓解内部碎片。
- 基于 Yi-6B、Llama-3-8B、Yi-34B 的系统评测表明，vAttention 在长上下文端到端吞吐上较 PagedAttention 版 FlashAttention-2/FlashInfer 最高提升 1.18×/1.23×，解码吞吐较 vLLM 最高提升 1.99×。

局限：

- 论文明确将“更复杂的策略如将 KV cache 换出到 CPU 内存”留作未来工作，因此 vAttention 目前未实现 CPU 换出/交换。
- 为了支持 64KB 等小页分配，需要修改开源的 NVIDIA 统一内存驱动；若无法接受驱动修改，则仅能用 2MB 页或依赖张量切片来降低碎片。
- FlashInfer 的非 paged decode 内核本身延迟显著更高（高达 14.6×），因此在该评估中未采用它作为 vAttention 的 decode 后端。

证据：

- vAttention 的核心设计是通过利用系统对按需分页的支持，将虚拟内存分配与物理内存分配解耦，从而在保留 KV cache 虚拟连续性的同时实现动态物理内存管理，而不是像 PagedAttention 那样在用户态实现按需分页。 — “To realize this, vAttention decouples the allocation of virtual memory from physical memory by leveraging system support for demand paging (instead of implementing demand paging in user space, as in PagedAttention).”，p. 5
- 实验结果表明，vAttention 在解码吞吐和长上下文端到端吞吐上均优于 PagedAttention 对比方案：使用非 paged FlashAttention-2 内核时解码吞吐最高比 vLLM 提升 1.99×，端到端长上下文吞吐最高比 PagedAttention 版 FlashAttention-2 和 FlashInfer 提升 1.18× 和 1.23×。 — “Using FlashAttention-2’s non-paged attention kernel, vAttention outperforms vLLM by up to 1.99× in decode throughput. In long-context scenarios, it also improves the end-to-end LLM serving throughput by up to 1.18× and 1.23× over PagedAttention based kernels of FlashAttention-2 and FlashInfer”，p. 2

### P04 · BurstGPT: A Real-world Workload Dataset to Optimize LLM Serving Systems

BurstGPT 是一个包含 213 天、1031 万条 Azure OpenAI GPT 真实服务轨迹的公开数据集，刻画了请求并发突发性、对话模式、模型响应长度和系统失败特征，用于指导 LLM 服务系统在真实负载下的评估与优化。

- 分类：推理服务与请求调度, KV Cache与内存管理, 性能评测与成本分析, 可靠性、弹性与可观测性
- 研究问题：面向 LLM 服务优化的突发性、对话模式和失败模式应如何刻画？具体而言，真实负载中的请求并发突发性、多轮对话结构和系统失败是否暴露了现有调度、KV Cache 管理与 PD 分离优化在非真实或合成负载下被忽视的问题？
- 方法：论文在 Azure OpenAI GPT 服务的一个区域服务提供商处部署日志引擎，收集 213 天隐私无关的请求元数据（请求开始时间、请求与响应 token 长度、API/对话服务类型、GPT 模型类型以及失败记录），形成 cleaned trace 和 raw trace。作者开源 BurstGPT-Perf 基准套件，提供两种扩展方法：RPS Scaling 直接缩放原始 trace，Modeled Scaling 以 20 分钟间隔用 Gamma 分布模拟请求并发、用 Zipf 分布模拟请求长度；通过 vLLM 等系统评测延迟、吞吐、抖动和失败率，并演示调度策略选择、负载预测与 PD 分离工业原型。
- 实验设置：演示实验使用 Llama-2-13b-chat（部分实验为 7b）在单张 A800 和 A6000 GPU 上运行 vLLM；Modeled Scaling 初始参数为 Gamma alpha=0.5、Gamma beta=2、Zipf theta=1.1，目标为 30% GPU KV Cache 利用率，请求池使用 ShareGPT。与 MAF2 对比时，将二者 RPS 均缩放至 0.326，在 6126 秒内完成；调度实验比较 FCFS、SRF、LRF；负载预测使用 XGBoost，以过去 3 个时间点和滚动统计特征预测请求数与平均 token 数；PD 分离模拟固定 8 个实例，比较固定 P:D 比例与基于 beam search 的动态比例。
- 与综述主题的关系：该论文直接服务 AI Infra 推理系统优化：它不是提出新的调度或内存算法，而是提供真实负载数据集与评测方法，揭示突发请求、短对话、高失败率等实际模式，用于评估和指导 vLLM 等系统的请求调度、KV Cache 内存管理、PD 分离和负载预测，从而提升吞吐、延迟、成本效率与可靠性。
- 置信度：0.95

主要贡献：

- 发布了包含 10.31 million 条 traces、覆盖 213 天的真实世界 LLM 服务工作负载数据集 BurstGPT，并同时提供 cleaned trace 与 raw trace。
- 从用户、模型和系统视角刻画了用户请求并发、对话模式、模型响应长度和系统响应失败四类特征，区别于现有 MAF/合成负载。
- 开源轻量模块化基准套件 BurstGPT-Perf，支持 RPS Scaling 和 Modeled Scaling，便于对任意规模服务系统进行可扩展评估。
- 通过演示评估发现非 LLM/合成负载不能准确反映 LLM 服务性能，且同一优化（如 LRF 调度）在不同服务类型间不保证泛化。
- 展示了 BurstGPT 在工作负载预测与 PD 分离系统动态比例选择中的工业应用。

局限：

- 轨迹来自单一区域 GPT 服务提供商（超过 3000 用户），可能无法代表所有云区域、模型版本或部署形态。
- 对 Llama-2-13b-chat 的对比使用从 ShareGPT 随机截断并对齐分布的提示，而非真实用户对话，可能影响响应长度对比的生态效度。

证据：

- 对话请求高度集中于短会话：超过35%的对话仅含一个请求，中位数为2，75%的对话不超过4个请求。 — “Over 35% of conversations end with only one request. The left of Figure 9 shows that the distribution of conversation requests exhibits an exponential decline, with a median of 2 and 75% of conversations with four or fewer requests.”，p. 4
- BurstGPT 中的失败率较高，主要由 KV cache 管理低效导致；突发性变化造成内存瓶颈，引发失败率尖峰和性能下降。 — “We observe a relatively high failure rate in BurstGPT. In our evaluation, we identify that this is primarily due to inefficiencies in KV cache management. Variations in burstiness in BurstGPT lead to memory bottlenecks, causing spikes in failure rates and performance degradation.”，p. 2

### P05 · NanoFlow: Towards Optimal Large Language Model Serving Throughput

NanoFlow 提出一种面向大语言模型在线推理的服务框架，通过将输入拆分为 nano-batches 并在单个 GPU 内重叠计算、内存与网络操作，从而提升端到端服务吞吐并接近理论最优。

- 分类：推理服务与请求调度, 并行计算与分布式执行, KV Cache与内存管理, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？本文聚焦其中的吞吐与并行执行问题：NanoFlow 如何通过 nano-batching 实现单个 GPU 内异构资源（计算、内存、网络）的重叠，以提升 LLM 服务吞吐。
- 方法：论文首先对 LLM serving 的 memory、compute、network 延迟建立成本模型（Tmem、TCompute、Tnet），论证现代 LLM serving 整体处于 compute-bound 区域；随后提出 NanoFlow，包含两阶段 auto-search：阶段一使用混合整数线性规划（MILP）确定 nano-operation 的数量、batch size 与执行顺序（暂不考虑 kernel 干扰），阶段二结合 kernel interference profiling 和 R→P 资源映射表细化 GPU 资源分配；运行时通过异步批处理、PagedAttention 式 KV-cache 管理以及分层（CPU/SSD）KV-cache 卸载来执行自动生成的流水线。
- 实验设置：在 8×A100 80GB SXM（NVLink 互联）上评估，主要模型为 LLaMA-2-70B，另包括 LLaMA-3-70B、LLaMA-3-8B、Qwen2-72B、Deepseek-67B、Mixtral 8×7B；基线为 vLLM、DeepSpeed-FastGen、TensorRT-LLM；数据集为 Splitwise、LMSYS-Chat-1M、ShareGPT；使用 FP16 权重与激活，进行离线吞吐和在线延迟实验，并以 CUTLASS 测得的 LLaMA-2-70B 最优吞吐 1857 tokens/s/GPU 为参照。
- 与综述主题的关系：该论文直接面向 LLM 在线推理的吞吐优化，属于 AI Infra Systems 中推理服务与请求调度、并行计算与分布式执行、KV Cache 与内存管理、性能评测与成本分析等主题；其 intra-device parallelism 和 nano-batching 与 vLLM 等系统的 continuous batching、PagedAttention 等机制互补，展示了通过软硬件协同与细粒度资源重叠来提高 GPU 利用率和降低单位 token 成本的路径。
- 置信度：0.95

主要贡献：

- 详细分析并经验验证了现代 LLM serving 工作负载整体处于 compute-bound 区域，并推导了理论最优吞吐公式。
- 提出 NanoFlow，包括自动搜索 nano-batch 流水线的 auto-search 引擎和端到端 LLM serving runtime。
- 综合评估显示 NanoFlow 相较 vLLM、DeepSpeed-FastGen、TensorRT-LLM 等基线取得平均 1.91× 吞吐提升，并可达到理论最优吞吐的 50%-72%。

局限：

- NanoFlow 面向吞吐优先场景，在低请求率下延迟与最优基线相当但略高。
- 仅拆分 nano-batch 而不配合重叠调度会带来 13.2% 的性能下降，说明其收益依赖精确的调度与资源分配。
- KV-cache 分层卸载会因 kernel interference 使 pipeline 慢 3.0%，虽然可减少多轮对话中的重复计算。
- 实验集中在 NVIDIA A100 GPU 上，未覆盖其他厂商加速器或多节点/大规模流水线并行部署。
- NanoFlow 假设外部控制平面负责 auto-scaling、负载均衡和优先级路由，自身面向请求充足且均匀优先级的高吞吐场景。

证据：

- NanoFlow 通过将输入拆分为更小的 nano-batches 并复制操作，使各 nano-operation 独立处理不同数据，从而在单个设备内实现异构资源（计算、内存、网络）的重叠。 — “NanoFlow splits inputs into smaller nano-batches and duplicates operations to operate on each portion independently, enabling overlapping.”，p. 1
- NanoFlow 自动生成的执行管线通过重叠计算密集型、内存密集型和网络密集型操作来提高 compute 利用率与 serving 吞吐。 — “By overlapping the compute-, memory-, and network-intensive operations, NanoFlow increases compute utilization and improves the serving throughput.”，p. 11

### P06 · Llumnix: Dynamic Scheduling for Large Language Model Serving

Llumnix 通过跨模型实例的运行时请求重调度和 KV cache 实时迁移，将负载均衡、去碎片化、优先级隔离和自动扩缩容统一为基于虚拟用量的动态调度策略，从而显著改善尾延迟、高优先级请求加速和成本效率。

- 分类：推理服务与请求调度, KV Cache与内存管理, 性能评测与成本分析, 可靠性、弹性与可观测性
- 研究问题：请求状态的实时迁移如何在多个模型实例之间实现动态调度？
- 方法：论文提出 Llumnix，在 vLLM 等推理引擎之上实现调度层。核心机制是请求的 live migration：利用 KV cache 的 append-only 特性，将 KV cache 拷贝与解码计算多阶段流水线重叠，并通过源/目标实例之间的握手协议处理预分配、中止和提交。调度架构采用全局调度器加每实例 llumlet 的分布式设计，全局调度只基于实例负载而非单个请求状态。调度策略引入 virtual usage（虚拟用量）统一负载均衡、去碎片化、优先级隔离和自动扩缩容：排队请求、高优先级请求和终止实例会被赋予额外虚拟用量，使实例虚拟过载，从而触发迁移。实现约 3300 行 Python，使用 Ray actor 管理和 Gloo 传输 KV cache。
- 实验设置：在 16 块 A10 GPU 集群（4 台 ecs.gn7i-c32g1.32xlarge，每台 4 卡）上评测 LLaMA-7B 和 LLaMA-30B，使用 ShareGPT、BurstGPT 真实轨迹以及幂律合成长度分布、Poisson/Gamma 到达过程，与 round-robin、INFaaS++ 和 Llumnix-base 对比；另用 64 个 LLaMA-7B 实例的睡眠模拟进行调度压力测试。
- 与综述主题的关系：该论文聚焦在线推理阶段的请求调度与 KV Cache 内存管理，直接回答 AI Infra 如何通过跨实例动态调度和内存状态迁移改善吞吐、延迟、成本效率与 SLO：以运行时重调度替代一次性分发，缓解负载不均、内存碎片化和优先级干扰，并通过自动扩缩容提升成本效率，与 vLLM 等单实例引擎形成互补。
- 置信度：0.95

主要贡献：

- 揭示 LLM 服务中异构、不可预测请求带来的隔离、碎片化和优先级等调度挑战。
- 提出基于 KV cache 实时迁移的请求重调度机制，实现近零且与序列长度基本无关的停机时间。
- 设计全局调度器与 llumlet 结合的分布式调度架构，使连续动态重调度具备可扩展性。
- 提出 virtual usage 抽象，用统一负载均衡策略表达去碎片化、优先级和自动扩缩容等多重目标。
- 实现并开源 Llumnix，在尾延迟、高优先级加速和成本节省上优于对比系统。

局限：

- 目前仅支持 vLLM 作为后端推理引擎，对其他引擎的可扩展性尚未验证。
- 当前优先级只支持 high 和 normal 两类。
- virtual usage 规则采用简单启发式，例如排队请求直接使用真实内存需求，更多策略调优留作未来工作。
- 尚未支持跨多个模型类型/变体的调度，论文将其列为未来工作。

证据：

- Llumnix 利用 KV cache 只追加不改写的特性，将 KV cache 拷贝与解码计算流水线重叠，从而实现迁移期间的近零停机。 — “The live migration mechanism of Llumnix utilizes the inherent append-only characteristic of KV cache to pipeline the KV cache copying with the decoding computation.”，p. 5
- 在分布式调度架构下，Llumnix 用动态调度策略将不同目标的重调度场景统一起来，而该策略正是基于请求迁移带来的调度灵活性。 — “Llumnix further introduces a dynamic scheduling policy under this architecture that unifies all the rescheduling scenarios with different goals elegantly.”，p. 2

### P07 · KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache

提出KIVI，一种无需微调的2bit KV Cache非对称量化方法，按通道量化key cache、按token量化value cache，在几乎不损失生成质量的情况下降低峰值内存、增大batch size并提升推理吞吐。

- 分类：KV Cache与内存管理, 模型压缩与低精度计算, 推理服务与请求调度
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：论文首先对主流LLM的KV cache元素分布进行量化误差分析，发现key cache存在固定的大幅值通道而value cache没有明显离群模式；因此提出key cache按通道（per-channel）量化、value cache按token（per-token）量化的非对称2bit量化算法KIVI。为适配自回归推理的流式特性，KIVI将KV cache分为grouped部分和residual部分，grouped部分用低精度分组量化存储，residual部分保持全精度滑窗；在系统实现上，使用CUDA将反量化与矩阵乘法融合（Q_MatMul），并用Triton实现分组量化kernel。
- 实验设置：基于Hugging Face Transformers实现，评估Llama/Llama-2、Falcon、Mistral模型；任务包括LM-Eval（CoQA、TruthfulQA、GSM8K）、LongBench子任务和Needle-in-a-Haystack；默认量化group size G=32，residual length R=128（也评估R=32）；效率实验在单张NVIDIA A100 80GB上进行，使用基于ShareGPT的合成工作负载（平均输入长度161、输出长度338），在内存耗尽前增大batch size并比较峰值内存和吞吐。
- 与综述主题的关系：该工作属于KV Cache与内存管理以及低精度计算方向：通过按通道/按token的非对称2bit量化显著压缩KV cache占用，直接缓解长上下文和大batch在线推理中的显存瓶颈，使计算核心减少因加载KV cache而空闲的时间，从而增大batch size并提升吞吐。论文也指出KIVI与vLLM/PagedAttention等系统级内存管理优化正交，可叠加使用。
- 置信度：0.97

主要贡献：

- 对常见LLM的KV cache元素分布与量化误差进行深入分析，指出key cache应按通道量化、value cache应按token量化，并从离群通道与注意力稀疏性角度解释原因。
- 提出无需微调、即插即用的2bit KV cache量化算法KIVI，并给出适配流式解码的grouped/residual拆分数据结构。
- 提供硬件友好的CUDA/Triton实现，将反量化与矩阵乘法融合，支持与weight-only量化等方法组合。
- 在Llama、Falcon、Mistral上验证KIVI可将KV cache压缩到2bit，峰值内存降低2.6倍，支持最高4倍batch size并带来2.35倍到3.47倍吞吐提升。

局限：

- 对Falcon-7B这类multi-query attention模型，2bit KIVI可能有较大精度下降，需要使用4bit KIVI。
- 在GSM8K等困难生成任务上，完全2bit fake量化精度显著下降，KIVI依赖全精度滑动窗口缓解，但残差长度对精度没有一致规律（R=64效果最差）。
- 论文指出当前吞吐提升还可通过进一步将KV cache量化过程与前序算子融合来增大，该优化留作未来工作。

证据：

- 论文通过分布分析发现，key cache应沿通道维度分组量化，而value cache应沿token维度量化。 — “Our findings indicate that the key cache should be quantized per-channel, i.e., group elements along the channel dimension and quantize them together. In contrast, the value cache should be quantized per-token.”，p. 1
- KIVI在保持模型质量几乎不变的情况下减少峰值内存，从而支持更大batch size并获得明显吞吐提升。 — “With hardware-friendly implementation, KIVI can enable Llama, Falcon, and Mistral models to maintain almost the same quality while using 2.6× less peak memory (including model weight). This reduction in memory usage enables up to 4× larger batch size, bringing 2.35× ∼3.47× throughput on real LLM inference workload.”，p. 1

### P08 · INT-FlashAttention: Enabling Flash Attention for INT8 Quantization

INT-FlashAttention 提出首个与 FlashAttention 前向流程兼容的 token-level INT8 后训练量化架构，用 INT8 GEMM 替换所有矩阵乘法，在 RTX4090 上相比 FlashAttention-FP16 推理时间最多降低 73%，并比 FlashAttention-FP8 在均匀分布激活下最多减小 82% 的量化误差。

- 分类：模型压缩与低精度计算, 异构硬件与内核优化
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：论文基于 FlashAttention 的前向流程，提出 token-level 线性对称后训练量化架构。Q/K 使用 per-token 缩放因子，V 使用 tensor-level 缩放因子，将 Q、K、V 量化为 INT8。注意力分数通过 INT8 GEMM 计算后乘以缩放因子得到 FP32 的 S；在线 softmax 中将指数归一化后的注意力权重 P 量化为 INT8，并通过缩放因子隐式并入 l 的累积和最终反量化，使输出与标准 softmax/FP32 计算结果等价。所有矩阵乘法均替换为 INT8 GEMM（INT32 累加），从而适配 FlashAttention 的 tiling 与 online softmax 流程。
- 实验设置：在 NVIDIA RTX4090 GPU 上使用 Triton 实现 INT-FlashAttention、半 INT8 变体、FlashAttention-FP16 和 FlashAttention-FP8，固定 batch size、head 数和每 head 维度，测量序列长度为 1k/2k/4k/8k/16k 的推理时间；量化精度上使用合成单层自注意力模块，Q/K/V 激活分别服从 N(0,1) 和 U(-0.5,0.5)，以 Mean Relative Error (MRE) 比较原始激活与量化再恢复后的误差。
- 与综述主题的关系：该论文聚焦低精度计算与内核级优化：将 INT8 量化与 FlashAttention 的 tiling 和 online softmax 有机结合，使用 INT8 GEMM 替换 FP16/FP8 GEMM，在保持输出等价性的前提下提升注意力前向推理速度并降低量化误差，直接服务于 AI Infra 中通过低精度计算和软硬件协同优化大模型在线推理吞吐与延迟的目标。
- 置信度：0.90

主要贡献：

- 提出 INT-FlashAttention，一种可无缝集成到 FlashAttention 前向工作流的 token-level 后训练量化架构。
- 实现 INT8 原型，Q、K、V 全部为 INT8，并使用 INT8 GEMM 替换推理中的所有矩阵乘法；作者声称这是首个 fully INT8 input 的注意力算子。
- 实验表明相比 FlashAttention-FP16，INT-FlashAttention 显著提升推理速度，并相比 FlashAttention-FP8 实现更低的量化误差。

局限：

- V 矩阵目前仅实现了 tensor-level 量化，尚未实现 per-token 量化。
- 未来工作计划使用 per-block 量化优化 V 矩阵，并探索与 Hadamard 变换结合以进一步加速推理。

证据：

- INT-FlashAttention 是首个与 FlashAttention 前向流程兼容的 INT8 量化架构，能显著提升 Ampere GPU 上 FlashAttention 的推理速度。 — “This paper introduces INT-FlashAttention, the first INT8 quantization architecture compatible with the forward workflow of FlashAttention, which significantly improves the inference speed of FlashAttention on Ampere GPUs.”，p. 1
- INT-FlashAttention 原型将 Q、K、V 矩阵实现为 INT8，并用 INT8 GEMM 替换推理中的所有矩阵乘法，从而提升推理速度并节省能耗。 — “We implement our INT-FlashAttention prototype with INT8-type Q, K, and V matrices. We use INT8 general matrix-multiplication (GEMM) kernels to replace all matrix multiplications during inference, thus significantly improving inference speed and saving energy.”，p. 2

### P09 · CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion

CacheBlend 通过只选择性重算少量 token 的 KV cache 来融合多个预计算 KV cache，在恢复文本块间 cross-attention 的同时显著降低 RAG 场景的 TTFT 并提高推理吞吐。

- 分类：KV Cache与内存管理, 推理服务与请求调度
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：CacheBlend 以逐层方式融合预先计算的 KV cache：在每一层只对少量 HKVD（高 KV 偏差）token 重算 KV，其余 token 的 KV 直接复用；利用相邻层 KV 偏差排名的相关性，通过逐层渐进过滤筛选需重算的 token；同时把 KV cache 加载与选择性重计算流水线化，并用 loading controller 选择重算比例和存储设备。系统在 vLLM 上实现，包含 KV cache store、fusor 和 loading controller 三个核心组件。
- 实验设置：实现基于 vLLM，约 3K 行 Python/PyTorch 代码；在 Runpod GPU（128GB RAM、2 块 Nvidia A40、1TB NVME SSD，实测吞吐 4.8 GB/s）上评测 Mistral-7B、Yi-34B 和 Llama-70B（后两者采用 8-bit 量化）；数据集包括 2WikiMQA、Musique、SAMSum、MultiNews 以及 Musique/2WikiMQA extended 合成复用数据集；对比 Full KV recompute、Prefix caching、Full KV reuse、MapReduce 和 MapRerank。
- 与综述主题的关系：该工作直接面向 LLM 推理系统中的 KV cache 复用与内存管理：CacheBlend 在 vLLM 之上实现非前缀 KV cache 的融合与选择性重计算，并通过流水线化 KV 加载与计算来优化 RAG 在线推理的 TTFT 和吞吐，是 AI Infra 中请求调度、缓存管理与软硬件协同的一个具体实例。
- 置信度：0.95

主要贡献：

- 提出 CacheBlend，使 RAG 中多个非前缀文本块的预计算 KV cache 可以被快速融合，并通过选择性 KV 重计算保持与 full prefill 相近的生成质量。
- 提出基于 KV deviation 的 HKVD token 选择机制及逐层渐进过滤方案，利用注意力/ KV 偏差稀疏性与相邻层相关性大幅减少需要重算的 token 数。
- 设计 fusor、KV cache store、loading controller，将 KV cache 加载与部分重计算流水线化，从而允许使用更慢但更便宜的存储设备而不增加 TTFT。
- 在 vLLM 上开源实现并系统评测，展示相对 full KV recompute 的 2.2–3.3× TTFT 降低和 2.8–5× 吞吐提升。

局限：

- 论文方法目前仅适用于 transformer 结构的语言模型，未覆盖 Mamba、Griffin 等非 transformer 架构。
- 评测尚未覆盖更多模型和数据集以及不同量化设置。
- CacheBlend 集成在 vLLM 中，但尚未在 Distserve、StableGen 等最新 serving engine 上测试。
- 尚未研究跨不同计算节点共享 KV cache 的工作负载场景。

证据：

- CacheBlend 通过选择性重算一小部分 token 的 KV cache 来融合多个预计算 KV cache，使非前缀文本块也能在保持质量的前提下被复用。 — “We present CacheBlend, a system that fuses multiple pre-computed KV caches, regardless of prefix or not, by selectively recomputing the KV cache of a small fraction of tokens, based on the preceding texts in the specific LLM input.”，p. 2
- 生成质量保持的关键在于恢复文本块之间的 cross-attention，具体做法是只重算少量 token 的 KV cache 值。 — “To preserve generation quality, CacheBlend recovers the cross-attention among these texts by selectively recomputing the KV cache values of a small fraction of tokens.”，p. 13

### P10 · CacheGen: KV Cache Compression and Streaming for Fast Large Language Model Serving

CacheGen 是一个面向 LLM 服务的快速上下文加载模块，通过利用 KV cache 的分布特性进行 delta 编码、分层量化和算术编码压缩为 bitstream，并在流式传输时按带宽自适应调整压缩级别，从而显著减少 KV cache 传输带宽和 TTFT，同时保持生成质量。

- 分类：KV Cache与内存管理, 模型压缩与低精度计算, 推理服务与请求调度
- 研究问题：如何利用 KV cache 的分布特性（token 局部性、层间敏感性、channel/layer 分组）进行压缩编码与带宽自适应流式传输，从而在不损害生成质量的前提下降低 KV cache 传输带宽和上下文加载延迟？
- 方法：CacheGen 先基于三个经验洞察设计 KV cache 编码器：利用 token-wise locality 对相邻 token 计算 delta 张量；利用 layer-wise loss sensitivity 对浅层采用更保守的量化、深层采用更粗的量化；利用 channel/layer 分组的信息增益，按 channel-layer 组合用 GPU 加速的算术编码将量化后的 delta 和 anchor 张量压缩为 bitstream。随后设计 KV cache streaming：将上下文分成多个 chunk，每个 chunk 离线编码为多个压缩级别，传输时根据实测吞吐估计剩余时间并选择满足 SLO 的配置，必要时回退到文本格式让 LLM 重算 KV；同时将解码与传输流水线化以降低额外延迟。
- 实验设置：在配备 NVIDIA A40 GPU 的服务器（384GB 内存、Intel Xeon Gold 6130 CPU）上，使用 Mistral-7B、Llama-34B、Llama-70B 三个模型，以及 LongChat、TriviaQA、NarrativeQA、WikiText 四个数据集共 662 个上下文（1.4K 到 16K tokens）评估；基线包括 default quantization、text context（vLLM 实现）以及 H2O 和 LLMLingua 等上下文压缩方法。
- 与综述主题的关系：该工作聚焦 AI Infra 中的 KV Cache 与内存管理、模型压缩与低精度计算、推理服务与请求调度等方向：通过分布感知编码压缩 KV cache 降低网络带宽占用，通过流式分块与压缩级别自适应在动态带宽下满足 TTFT SLO，从而提升在线推理的延迟、吞吐与成本效率，并且可与 vLLM 等 serving 系统互补结合。
- 置信度：0.93

主要贡献：

- 设计自定义 KV cache 编码器，利用 token-wise locality、layer-wise loss sensitivity 和 channel/layer grouping 三类分布特性，将 KV cache 编码为更紧凑的 bitstream，而不是保持原始张量格式。
- 提出 KV cache 流式传输机制，将上下文分块并预编码多个压缩级别，根据带宽动态选择压缩级别或回退到文本计算，以在 SLO 内完成上下文加载。
- 实现 GPU 加速的算术编码/解码，并将解码与网络传输流水线化，使解码开销对端到端延迟影响最小。
- 与 H2O、LLMLingua 等上下文压缩方法互补，可进一步压缩其产生的 KV cache，并集成到 HuggingFace 与 LangChain。

局限：

- 未在超大模型（如 OPT-175B）上评估，受限于 GPU 内存。
- 未广泛评估 free-text generation 任务（如故事生成），因为质量指标不如评测任务明确。
- 网络模型未包含极高带宽条件；在非常高算力 GPU 且相对低带宽下，相比 text context 基线的改进可能有限。
- 真实场景中上下文复用缺乏公开产业数据集支撑，论文主要依赖轶事证据。
- 实验中 H2O 是使用 prompt query 张量的理想化版本。

证据：

- 与现有复用 KV cache 的系统相比，CacheGen 将 KV cache 大小降低 3.5-4.3 倍，并将获取/处理上下文的总延迟降低 3.2-3.7 倍，同时生成质量几乎不受影响。 — “Compared to the recent systems that reuse the KV cache, CacheGen reduces the KV cache size by 3.5-4.3x and the total delay in fetching and processing contexts by 3.2-3.7x with negligible impact on the LLM response quality.”，p. 1
- CacheGen 在流式传输中按 chunk 自适应调整压缩配置，使 KV cache 传输延迟保持在 SLO 内，这是其应对带宽波动、保持低延迟和高生成质量的关键机制。 — “CacheGen adapts the configuration of each chunk while streaming the KV cache to keep the transmission delay within an SLO.”，p. 7

### P11 · Stateful Large Language Model Serving with Pensieve

Pensieve 是一个面向多轮对话的状态化 LLM 推理服务系统，通过 GPU/CPU 多级 KV 缓存保存并复用已处理的历史上下文，并扩展 PagedAttention 支持非连续内存上的多 token 注意力，从而避免重复历史处理并提升吞吐、降低延迟。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 异构硬件与内核优化
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：论文设计并实现了 Pensieve：调度器执行迭代级统一批处理，将 prefill 和 generation 阶段的请求合并；缓存管理器以 token 块为粒度在 GPU/CPU 间换入换出 KV-tokens，采用基于重算成本和 LRU 的保留值驱逐策略，并使用 ahead-of-time swapping 和 pipelined recovery 隐藏数据传输延迟；新实现基于 Cutlass 的多 token 注意力 kernel 处理非连续 KV 缓存和因果掩码，并通过 Megatron-LM 的张量并行支持多 GPU。
- 实验设置：在 Azure NC A100 v4 系列（最多 4×A100-80GB，每 GPU 配 220GB CPU 内存）上评估 OPT-13B/OPT-66B 和 Llama 2-13B/Llama 2-70B（后者使用 GQA），使用 ShareGPT 和 UltraChat 两个多轮对话数据集，模拟泊松请求到达和指数用户思考时间；对比 vLLM v0.2.0 和 TensorRT-LLM v0.12.0，并包含仅 GPU 缓存的 Pensieve 变体；衡量吞吐和 90 百分位归一化延迟。
- 与综述主题的关系：论文直接回应 AI Infra Systems 中的 KV Cache 与内存管理、推理服务与请求调度、异构硬件与内核优化等核心问题：用 CPU 内存扩展 GPU 缓存容量，以设备间换入换出和流水线恢复隐藏 PCIe 传输延迟，并用统一批处理和多 token 注意力提升 GPU 利用率，从而改善大模型在线推理的吞吐和延迟。
- 置信度：0.95

主要贡献：

- 识别出多轮对话场景中现有无状态 LLM serving 系统反复重算会话历史的主要低效。
- 设计并实现状态化 serving 系统 Pensieve，用多级 GPU-CPU 缓存跨请求保存并复用 KV-tokens，支持 token 块级换入换出与丢弃重算。
- 实现广义 PagedAttention 的多 token 注意力 GPU kernel，支持 KV 缓存驻留在非连续 GPU 内存上，并统一批处理 prefill 与 generation 阶段。
- 在真实对话数据集上相对 vLLM 和 TensorRT-LLM 实现 1.14-3.0× 的吞吐提升。

局限：

- Pensieve 只在本地 GPU 和 CPU 内存中保留 KV 缓存，不覆盖远程网络存储/流式 KV 缓存传输场景，论文将 CacheGen 的相关技术视为正交。
- Pensieve 和 vLLM 使用 PyTorch API 执行模型，而 TensorRT-LLM 通过图重写和算子融合离线优化，因此在部分小模型负载下 TensorRT-LLM 可优于 Pensieve 的仅 GPU 缓存变体。

证据：

- Pensieve 的多层缓存策略同时利用 GPU 和 CPU 内存来高效存储与取回缓存数据。 — “multi-tier caching strategy can utilize both GPU and CPU
memory to efficiently store and retrieve cached data.”，p. 1
- Pensieve 将 PagedAttention 推广为支持多个输入 token 的注意力计算，以处理 KV 缓存散落在非连续 GPU 内存上的情况。 — “also generalizes the recent PagedAttention kernel to support
attention between multiple input tokens with a GPU cache
spread over non-contiguous memory.”，p. 1

### P12 · FastSwitch: Optimizing Context Switching Efficiency in Fairness-aware Large Language Model Serving

FastSwitch 面向公平性驱动的 LLM 推理服务，通过动态块组 KV cache 管理、多线程异步交换和跨轮次 KV cache 复用，降低抢占式调度中上下文切换带来的 I/O 开销与 GPU 空闲，从而改进 TTFT/TBT 等 SLO。

- 分类：推理服务与请求调度, KV Cache与内存管理, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：论文剖析了现有 vLLM 式分页 KV cache 在公平性抢占调度中引发上下文切换开销的三个挑战：I/O 带宽利用不足、GPU 空闲、多轮对话中重复 I/O；对应设计 Dynamic Block Group Manager（buddy 式粗粒度块组分配）、Multithreading Swap Manager（异步/同步自适应交换并规避 Python GIL 与多流 cudaMemcpyAsync 顺序问题）、KV Cache Reuse Mechanism（跟踪 CPU 中未污染块组并预分配下一轮增量空间）。实现基于 vLLM，用约 5000 行 Python 和 1000 行 C++/CUDA，并使用 lightllm 的 prefill-with-prefix kernel。
- 实验设置：使用 LLaMA-8B 在 NVIDIA A10 24GB 和 Qwen-32B 在 A100 80GB 上评估，每个 GPU 配 60GB CPU swap 空间，PCIe 4.0 x16（理论单向 32GB/s 传输带宽）；数据集为 Multi-Round ShareGPT，随机选 1000 条多轮对话，平均 5.5 轮，泊松到达率 1 req/s；由于缺乏公开 LLMaaS 上下文切换 trace，按 (Yin et al., 2024) 模拟 Random 与 Markov 两种模式，优先级离线预计算；LLaMA-8B 使用 priority-update frequency 0.04，Qwen-32B 使用 0.02；基线是 vLLM 0.3.3，指标包括 P95/P99/P99.9 TTFT、P99.9 TBT 和端到端吞吐。
- 与综述主题的关系：论文属于以 vLLM 为代表的 LLM 推理系统研究，直接关注 KV cache 内存布局如何影响抢占式公平调度中的上下文切换成本：它指出 vLLM 的非连续分页块式 KV cache 虽减少内存碎片，却造成交换粒度小、PCIe I/O 带宽利用率差，并通过块组化内存分配、异步交换和跨轮 KV cache 复用等机制提升吞吐、尾部延迟和可靠性相关 SLO，与内存管理、请求调度、性能评测主题紧密相关。
- 置信度：0.90

主要贡献：

- 刻画并指出公平性感知 LLM 服务中优先级调整导致上下文切换开销的三个未解决挑战：I/O 未充分利用、GPU 空闲、多轮对话冗余 I/O。
- 提出 FastSwitch，包含 Dynamic Block Group Manager、Multithreading Swap Manager、KV Cache Reuse Mechanism，三者协同优化抢占式上下文切换效率。
- 在与 vLLM 的端到端对比中，报告 TTFT 最高 1.4-5.8×、TBT 最高 11.2×、吞吐最高 1.44× 的提升。

局限：

- 论文没有可用的真实 LLMaaS 上下文切换 trace，只能参照 (Yin et al., 2024) 模拟 Random/Markov 两种模式，且优先级是离线预计算而非运行时动态生成，可能低估真实在线调度中的复杂情况。
- 论文报告的实验配置只覆盖 LLaMA-8B 和 Qwen-32B 在 A10/A100 上的评估，未报告与 Llumnix、AttentionStore、FastServe 等方法的直接实验对比。

证据：

- FastSwitch 的核心观察是，现有系统的基于块的 KV cache 内存策略虽然近零内存浪费，却导致 KV cache 内存不连续且粒度不足，从而放大抢占式上下文切换开销。 — “Our key insight is that the block-based KV cache memory policy in existing systems, while achieving near-zero memory waste, leads to discontinuity and insufficient granularity in the KV cache memory.”，p. 1
- vLLM 的非连续分页 KV cache 在提高吞吐的同时会造成碎片化内存分配，进而在上下文切换时无法充分利用 PCIe I/O 带宽。 — “In existing system (Kwon et al., 2023), the non-contiguous paged memory for KV cache to achieve higher throughput causes fragmented memory allocation, leading to poor utilization of PCIe I/O bandwidth when context switching.”，p. 2

### P13 · Locality-aware Fair Scheduling in LLM Serving

该论文提出首个局部性感知的公平调度算法 DLPM 及其分布式扩展 D2LPM，通过带赤字的最长前缀匹配机制在保持前缀缓存局部性的同时提供公平性保证，从而提升 LLM 在线推理的吞吐并降低客户端延迟。

- 分类：推理服务与请求调度, KV Cache与内存管理, 并行计算与分布式执行, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：论文设计 DLPM：在每个连续批处理步骤中，先按最长前缀匹配长度对等待队列排序，但仅将赤字计数器 qi > 0 的客户端的请求加入当前批；当所有活跃客户端的 qi <= 0 时，按量子 Qu 补充计数器。该机制受 Deficit Round Robin 启发，在保持 LPM 局部顺序的同时偶尔优先服务较少被服务的客户端。分布式扩展 D2LPM 采用去中心化调度，为每个 worker 和客户端维护独立的赤字计数器，先利用全局 RadixTree 找到最长匹配前缀所在的 worker 集合，再在可用 worker 中选择队列最短者，以平衡局部性与负载均衡。作者给出服务界和延迟界的理论证明，并在 SGLang 上实现，与 VTC、RR+LPM、Preble 进行对比。
- 实验设置：实现基于 SGLang；模型使用 Llama-3.1-8B 和 Llama-3.2-3B；硬件为 NVIDIA A100 80GB 和 A10G GPU。工作负载包括 Long-Context QA（LooGLE）、Tree-of-Thoughts（GSM8K）、LLM-as-a-Judge 以及真实多轮对话（Chatbot Arena）。合成请求迹线按 Gamma 过程生成，并设置 S1（更多请求/更复杂执行图）和 S2（更长前缀）两类 misbehaving 客户端模式。基线包括 D2LPM（本地 DLPM）、RR+LPM、Preble 和 VTC；指标为服务速率、Jain 公平性指数以及 P50/P99 延迟（长上下文 QA 使用 TTFT）。
- 与综述主题的关系：论文聚焦 LLM 在线推理服务中的请求调度，是 AI Infra 系统中请求调度与 KV Cache/内存管理交汇点的代表性工作。DLPM/D2LPM 通过赤字计数器在保留 RadixAttention/前缀缓存局部性的同时提供公平性保证，直接影响 KV cache 复用率、批处理效率、端到端吞吐和客户端延迟；分布式 D2LPM 还显式处理局部性与负载均衡之间的权衡，与 vLLM、SGLang 等推理引擎的调度设计密切相关。
- 置信度：0.95

主要贡献：

- 提出首个局部性感知的 LLM 推理公平调度算法 DLPM 及其分布式版本 D2LPM。
- 为 DLPM 和 D2LPM 提供严格的公平性理论界，包括服务界和延迟界。
- 通过多工作负载、多 GPU 规模实验证明算法能在保证公平性的同时保持高吞吐和低延迟。

局限：

- 论文仅考虑同一客户端内部请求之间的前缀共享，忽略不同客户端请求之间的前缀共享。
- 调度算法未考虑程序内推理请求之间的数据依赖，例如上游请求生成下游请求输入时，优先调度上游请求可能带来更高并行度，但当前算法可能为了前缀共享或严格公平而错过这种机会。

证据：

- 论文声称其提出的 DLPM 和 D2LPM 在保证公平性的同时显著提升性能：与 VTC 相比吞吐最高提升 2.87 倍，与现有分布式 LLM 服务系统相比每客户端延迟最高降低 7.18 倍。 — “Our extensive evaluation demonstrates the superior performance of DLPM and D2LPM in ensuring fairness while maintaining high throughput (up to 2.87× higher than VTC) and low per-client (up to 7.18 × lower than state-of-the-art distributed LLM serving system) latency.”，p. 1
- DLPM 的核心机制是受 Deficit Round Robin 启发的量子机制，它迫使调度器偶尔优先处理服务较少的客户端请求，而不是始终选择最长前缀匹配的请求，从而在不彻底破坏 LPM 局部顺序的情况下引入公平性。 — “To achieve this, we incorporate a quantum mechanism inspired by the deficit round robin (DRR) approach [43]. This mechanism compels the scheduler to occasionally prioritize requests from less-served clients over those with the longest matching prefixes.”，p. 4

### P14 · DynaServe: Unified and Elastic Execution for Dynamic Disaggregated LLM Serving

DynaServe 提出 micro-request 抽象与两级调度，将共置与分离式 LLM serving 统一起来，在 100ms TBT SLO 下显著提升 goodput 与服务容量。

- 分类：推理服务与请求调度, KV Cache与内存管理, 并行计算与分布式执行, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：基于 vLLM 实现 DynaServe，提出 Adaptive Request Partitioning and Scheduling (APS)：每个请求可在任意 token 边界切成至多两个 micro-request；全局调度器使用轻量性能预测器和有界二分搜索快速选择切分点并路由；本地调度器依据 profile table 做 SLO-aware 批次组成；运行时采用 chunk-based KV cache transfer 支持跨实例微请求执行。在 A100 集群上使用 Qwen-2.5 系列模型和真实负载与 vLLM 共置/分离基线对比。
- 实验设置：两台服务器各含 4 张 NVIDIA A100 80GB GPU、128 CPU、1TB 内存、4×200Gbps RoCE NICs，使用 PyTorch 2.5.1 与 CUDA 12.4；模型为 Qwen-2.5-14B/32B/72B；负载包括 BurstGPT、Azure Code、arXiv Summarization、Mini Reasoning，请求到达服从 Poisson 分布；基线为 vLLM PD Colocation（chunked prefill）和 PD Disaggregation；SLO 为 100ms P99 TBT；DynaServe 与 PD Disaggregation 使用相同 GPU 数量，按 TP/DP 配置部署。
- 与综述主题的关系：核心相关：micro-request 抽象允许在任意 token 边界切分请求，使 prefill/decode 的放置不再局限于共置或分离二选一；两级调度在统一 GPU 池上按负载与 SLO 动态路由和分片，chunk-based KV transfer 则支撑跨实例状态传递。该设计直接面向在线推理的吞吐、延迟与成本效率，属于 AI Infra 系统中的请求调度、KV Cache/内存管理与分布式执行交叉方向。
- 置信度：0.95

主要贡献：

- 对 PD disaggregation 与 PD colocation 进行综合分析，指出其在不平衡动态负载下的尾延迟和吞吐缺陷。
- 提出 Adaptive Request Partitioning and Scheduling (APS) 与 micro-request 抽象，可在任意 token 边界将请求切分为最多两个协作 micro-request，并跨多个 GPU 动态执行。
- 设计两级动态调度框架，联合优化 micro-request 放置、批次组成与切分比例，在满足延迟 SLO 的同时最大化 GPU 利用率。
- 使用多种真实负载进行端到端评测，展示 DynaServe 相对共置和分离式基线的 goodput 与 serving capacity 提升。

局限：

- 论文未提供对超长上下文（如生产环境中超过百万 token）或超过 8 GPU 的更大规模集群的专门评估。
- 输出长度预测依赖现有方法；敏感性分析仅覆盖到 σ=100 的中等误差范围，极端预测偏差下的 SLO 保证未被充分说明。

证据：

- DynaServe 通过 micro-request 抽象（在任意 token 边界把一个请求切成至多两个协作片段）和两级调度框架，在统一 GPU 实例间平衡负载，从而支持灵活的 prefill/decode 放置。 — “It relies on a micro-request abstraction, which arbitrarily splits each request at any token boundary into at most two cooperating segments. A two-level scheduling framework then balances micro-request load across unified GPU instances.”，p. 1
- 相比 PD colocation 只能在 prefill 阶段内切分、PD disaggregation 只能在 prefill 与 decode 之间切分，APS 可在任意 token 位置切分请求，因而在放置空间上更灵活。 — “The abstraction makes APS more flexible than prior architectures: PD colocation partitions a request only within the prefill stage, while PD disaggregation splits a request strictly between prefill and decode. APS, on the other hand, can split a request at any token position.”，p. 5

### P15 · Nexus:Proactive Intra-GPU Disaggregation of Prefill and Decode in LLM Serving

Nexus 提出在单个 GPU/单个 serving engine 内对 prefill 与 decode 进行主动的逻辑解耦，通过动态 SM 分区、成本模型、滞回控制与相位专属调度来同时降低 TTFT/TBT 并保持高吞吐。

- 分类：推理服务与请求调度, 并行计算与分布式执行, 性能评测与成本分析
- 研究问题：Nexus 如何预测并适应同一 GPU 内 prefill 与 decode 不断变化的资源需求冲突，在保持高 GPU 利用率的同时优化 TTFT 与 TBT？
- 方法：Nexus 使用分析型成本模型预测不同 SM 分配下 prefill 与 decode 的延迟：算子级延迟取计算时间和内存时间最大值，计算时间采用双区段饱和-衰减曲线，内存时间显式建模 prefill/decode 的带宽竞争（通过注意力重叠概率）。在此基础上，Nexus 以 KV cache 占用率在 prefill-prioritized 与 decode-prioritized 两种目标间切换，并用贪心搜索（通常 2–4 次成本模型评估）求解分区；滞回缓冲避免频繁切换。prefill 采用 Shortest Prompt First，decode 采用 FCFS。实现上基于 vLLM 扩展，使用 CUDA Green Context 动态重分配 SM。
- 实验设置：评测平台为 Intel Xeon Platinum 8457C CPU 与两张 NVIDIA L20 48GB GPU，CUDA 12.8，PyTorch 2.6.0；模型包括 Qwen2.5-3B、LLaMA3.1-8B（单 GPU）与 Qwen2.5-14B（双 GPU）；工作负载为 Long Data Collections、Arxiv Summarization 和 Mixed（60% ShareGPT + 40% Long Data Collections），请求按 Poisson 过程到达；对比基线为 vLLM、FastServe、SGLang、vLLM-P/D；指标为 TTFT、TBT、Normalized Latency 及其 P95。
- 与综述主题的关系：Nexus 属于推理服务与请求调度方向，同时涉及并行计算与软硬件协同：它在单 GPU 内动态划分 SM 使 prefill 与 decode 并行执行，利用 KV cache 占用作为运行时反馈，并通过成本模型与贪心搜索实现资源自适应分配，直接服务于调查问题中吞吐、延迟、成本效率与可靠性的优化目标。
- 置信度：0.92

主要贡献：

- 提出 intra-engine prefill–decode disaggregation，在单个 serving engine 内逻辑分离两个阶段。
- 设计轻量级自适应调度机制：分析型成本模型、双目标贪心 SM 搜索、滞回缓冲控制和分阶段调度器。
- 作为 vLLM 的 drop-in 扩展实现（约 6K 行 Python/CUDA/C++），使用 CUDA Green Context 实现动态 SM 分区。
- 在多种生产规模模型和工作负载上评估，展示相比 vLLM、SGLang 和 vLLM-P/D 的吞吐与延迟优势。

局限：

- 论文未设独立 Limitations 节，但从实验结果可见：Mixed Workload 下因 prompt 长度多样性高，Nexus 的 P95 TTFT 较差；Arxiv Workload 下输入长度均匀导致动态分区较少触发，P95 TBT 落后。
- 当前实现针对 decoder-only LLM，且成本模型中的 R_sat 与 λ 等参数需要为每个模型和工作负载离线 profiling 标定。

证据：

- GPU 资源存在收益递减，Nexus 据此可以在单个 GPU 内动态分配资源给 prefill 与 decode，实现片内解耦。 — “Second, we find that GPU resource exhibits diminishing returns—beyond a saturation point, increasing GPU allocation yields negligible latency improvements. This insight enables us to split a single GPU’s resources and dynamically allocate them to prefill and decode on the fly, effectively disaggregating the two phases within the same GPU.”，p. 1
- Nexus 的三个核心组件构成闭环控制系统，能够持续调整 GPU 资源分配以适应负载变化，同时保持高利用率。 — “These components form a closed-loop control system that continuously adapts GPU resource allocation to match workload demands, preserving high utilization without reintroducing interference.”，p. 5

### P16 · Efficient LLM Serving on Hybrid Real-time and Best-effort Requests

BROS通过迭代级动态优先级调度与双向KV缓存块共享，将实时（RT）与尽力而为（BE）请求共置于同一LLM服务中，在显著降低RT延迟并提升SLO达成率的同时，仅以较小吞吐损失换取BE请求的持续处理。

- 分类：推理服务与请求调度, KV Cache与内存管理
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：BROS将混合RT/BE请求调度建模为迭代级选择问题的变体，目标是在满足每个RT请求TTFT/TPOT SLO约束下最大化BE请求吞吐。调度器使用基于剩余时间优先级的贪心打包算法：先按剩余SLO时间升序挑选RT请求，再在批未满或可替换低优先级RT请求时加入BE请求；并引入类似TCP拥塞控制的自适应批大小机制，根据运行时SLO达成情况动态调节批大小。为降低调度开销，采用部分排序和双队列轮询。KV缓存管理采用双向块布局，RT与BE请求在同一block内相向扩展存储KV cache，配合块抢占（block preemption）和lazy checkpointing，减少D2H交换与重算开销。实现上基于Ray、NCCL、PyTorch和Xformers，并修改PagedAttention kernel以支持双向方向和异步换入换出。
- 实验设置：评估使用OPT-13B、OPT-30B和Llama-3-70B模型；OPT实验在4张NVIDIA A100-40GB GPU上运行，Llama-3实验在8张A100-80GB GPU上运行，张量并行度分别为2、4、8。RT请求基于ShareGPT与LMSYS-CHAT-1M数据集合成，BE请求为FlexGen式合成工作负载（prompt长度U(512,1024)，输出长度U(32,128)）。基线包括vLLM、TGI和移除关键机制的BROS-RR。指标包括RT归一化延迟、TTFT/TPOT SLO达成率以及BE吞吐（req/s），所有实验使用10分钟traces，KV cache block size设为16。
- 与综述主题的关系：该工作聚焦AI推理系统中的内存管理与请求调度两大主题：vLLM以PagedAttention管理KV cache，BROS则进一步针对混合RT/BE负载引入双向KV块共享、迭代级抢占式调度和SLO感知批大小，直接回应了如何通过内存管理与请求调度提高大模型在线推理的延迟、吞吐与资源利用效率。
- 置信度：0.95

主要贡献：

- 提出BROS，一个面向混合RT/BE请求的LLM服务系统，旨在共置两类请求并同时满足RT延迟SLO与BE吞吐目标。
- 形式化混合RT/BE请求的迭代级调度问题，提出动态优先级打包算法与SLO感知的自适应批大小机制。
- 设计双向KV缓存管理机制，包括双向块布局、块抢占和lazy checkpointing，解决RT/BE请求间的GPU内存竞争。
- 在OPT和Llama模型及真实/合成负载上验证，相比vLLM、TGI和RR显著降低RT延迟并提升SLO达成率，同时保持较高BE吞吐。

局限：

- 论文指出没有代表性的BE请求数据集可用，因此BE请求采用FlexGen式合成工作负载，可能不完全反映真实BE流量分布。

证据：

- BROS采用双向KV块布局，使RT请求能够利用BE请求缓存块中的空槽，从而在不丢弃或换出KV cache的情况下解除内存不足对调度决策的限制。 — “a bidirectional block layout, which shares one block between two requests and increases their KV cache in the opposite direction, creates the opportunity for scheduled RT requests to utilize empty slots in the cache block from pending BE requests without KV cache dropping or swapping.”，p. 4
- BROS将每个KV cache block同时分给一个RT请求和一个BE请求，二者从块两端相向扩展，从而实现同一块内存的高效共享。 — “Each block can be used for KV cache storage of one RT request and one BE request, with a bidirectional storage layout for sharing the block between two requests: KV cache of the RT request occupies memory slots from the left to the right in the block while that of the BE request in the opposite direction.”，p. 7

### P17 · Tutti: Making SSD-Backed KV Cache Practical for Long-Context LLM Serving

Tutti 提出一种 GPU 中心化的 SSD-backed KV Cache 对象存储，通过 GPU io_uring 和 slack-aware I/O 调度消除 CPU 干预，使 vLLM 在长上下文场景中接近 DRAM 性能并大幅降低 TTFT 与服务成本。

- 分类：KV Cache与内存管理, 异构硬件与内核优化, 性能评测与成本分析
- 研究问题：针对长上下文 LLM 服务，如何通过 GPU-centric 存储消除 SSD-backed KV Cache 恢复时的 CPU 瓶颈，从而同时提升吞吐、降低延迟和成本？
- 方法：基于 GeminiFS 构建 GPU-centric 对象存储，将每个 KV block 映射为 GPU file 中的 key/value 对象；引入 P2P 内存映射表（采用 SGL 而非 PRP）支持 GPU 直访 SSD；设计 GPU io_uring (gio_uring)，利用 HBM 中的无锁 SQ/CQ 环和 SM 分区实现异步 GPU 直接对象 I/O；实现基于离线 profile 查找表的 slack-aware I/O 调度，将读写 I/O 放入计算 slack 窗口；集成到 vLLM 的 KVConnector，并通过 Mooncake 进行跨节点扩展。
- 实验设置：在 64 核 Intel Xeon 6530、512GB 内存、2×H100 80GB HBM、4×Solidigm D7-PS1010 7.68TB SSD 上，对比 vLLM 0.12.0/0.17.0 下的 HBM、DRAM（LMCache-DRAM-LW）、LMCache-SSD、LMCache-GDS 基线；模型使用 Llama3-8B（单 GPU）和 GLM-4-9B-Chat-1M（双 GPU 张量并行）；负载使用 LEval 和 LooGLE，并采用泊松到达模拟多会话；指标包括 TTFT、ITL、存储带宽、GPU bubble time 和每百万 token 成本。
- 与综述主题的关系：该工作属于 AI Infra 系统中 KV Cache 与内存管理、异构硬件与内核优化、性能评测与成本分析的交叉方向：Tutti 通过将存储 I/O 控制平面从 CPU 迁移到 GPU，结合 GPU io_uring 和 slack-aware 调度，展示了软硬件协同如何缓解长上下文 LLM 服务的 I/O 瓶颈，并与 vLLM 等推理引擎无缝集成，直接提升吞吐、降低延迟和成本。
- 置信度：0.95

主要贡献：

- 论文自述为首个消除 HBM 与 SSD 之间关键数据路径和 I/O 控制路径上 CPU 干预的开源 SSD-backed KV caching 解决方案。
- 提出 GPU-native 对象抽象，弥合 KV cache 传输与 GPU 存储 I/O 之间的粒度差距。
- 设计异步 GPU io_uring 和 slack-aware I/O 调度，实现计算与 I/O 深度重叠并避免资源争用。
- 集成到 vLLM，展示在饱和 NVMe SSD 带宽和降低 GPU stall 方面的有效性，并接近 DRAM-backed 性能、提供近无限容量。

局限：

- 当前原型未优化跨节点远程路径：使用 CPU 侧接口将 GPU file 读入 host memory 再经 RDMA 传输，增加了额外 CPU 开销。
- 论文展示的分布式评估为双 GPU 场景，跨节点远程加载仍依赖 Mooncake 协调，尚未实现论文提及的 GPU-initiated RDMA 直通远程路径。

证据：

- Tutti 的核心是 GPU-centric KV cache 对象存储，CPU 仅负责每层异步加载 I/O 内核，从而从 HBM 与 SSD 之间的关键数据路径和 I/O 控制路径中移除 CPU 干预。 — “At the core of Tutti is aGPU-centricKV cache object store, in which the CPU is only responsible forasynchronouslyloading I/O kernels once per layer to the GPU.”，p. 1
- 与最先进的 GDS-enabled SSD-backed LMCache 相比，Tutti 在严格 SLO 约束下将 TTFT 降低 78.3%，并将可实现请求速率提升 2 倍。 — “Extensive evaluation shows that compared to the state-of-the-art GDS-enabled, SSD-backed LMCache, Tutti reduces TTFT by 78.3% under strict SLO constraints and improves the achievable request rate by 2×.”，p. 1

### P18 · TraCT: Disaggregated LLM Serving with CXL Shared Memory KV Cache at Rack-Scale

论文提出 TraCT，将 CXL 共享内存同时用作机架级 KV 传输介质和前缀感知 KV 缓存，使 GPU 通过 CXL load/store 与 DMA 直接读写 KV 块，从而消除 RDMA/NIC 跳数，显著降低 TTFT 并提高吞吐。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 异构硬件与内核优化, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？本文聚焦其中的 KV Cache 跨节点共享：CXL load/store 与 DMA 如何替代 RDMA 成为机架级 KV 传输路径。
- 方法：本文采用系统设计、实现和受控对比评测的方法。作者分析了 CXL Type-3 设备缺少跨节点原子操作和全设备一致性的特点，提出了两层跨节点锁、基于 clflush 的元数据可见性机制、偏移寻址的共享内存分配器与对象存储，以及基于块哈希的前缀感知 KV 缓存。系统基于 NVIDIA Dynamo 和 vLLM 的 KV connector 层实现，并在真实 CXL 硬件上将 TraCT 与 NIXL/UCX 和 LMCache 基线进行对比。
- 实验设置：评估环境包含 2 台服务器：Server 1 运行基准客户端和除 prefill worker 外的运行时组件，Server 2 仅执行 prefill 任务。每台服务器配备 NVIDIA A6000 GPU（48 GB GDDR）和 512 GB 主机 DRAM；RDMA 基线使用 100 Gbps Mellanox MT2892 NIC；CXL 实验使用 Niagara 2.0 Type-3 内存扩展器，配置 64 GB 共享内存，MLC 测得访问延迟 640 ns、带宽 10.1 GB/s。软件栈为 Dynamo v0.5.0 + vLLM v0.10.1.1，模型为 DeepSeek-R1-Distill-Llama-8B。对比配置包括 NIXL/UCX、LMCache 和 TraCT；工作负载包括固定输入长度（1500/3000/4500/6000 token）的静态负载以及 Dynamo 生成器产生的合成负载 A/B/C。
- 与综述主题的关系：该论文直接回应调查问题中关于推理服务、内存管理和软硬件协同的部分：解耦式 LLM 服务的 KV 跨节点传输是关键瓶颈，TraCT 用 CXL 共享内存替代 RDMA，让 KV 块通过 load/store 和 GPU-CXL DMA 在机架内共享，从而降低延迟、提高吞吐和能效。这属于 KV Cache 与内存管理、推理服务与请求调度、异构硬件与内核优化以及性能成本分析的交叉研究。
- 置信度：0.92

主要贡献：

- 提出将 CXL 共享内存同时作为机架级 KV 传输层和前缀感知 KV 缓存，完全移除 RDMA/NIC 跳数。
- 设计并实现无硬件原子操作支持的两层跨节点锁，解决非一致 CXL 内存上的互斥问题。
- 提出基于 clflush 的细粒度缓存行刷新和元数据可见性策略，保证非相干共享内存上的正确性。
- 设计偏移寻址的共享内存分配器和对象存储，支持跨节点共享层级结构并降低元数据管理开销。
- 在 Dynamo-vLLM 上实现 TraCT，并在真实 CXL Type-3 硬件上展示其相对 RDMA/DRAM 缓存的性能优势。

局限：

- 评估只使用 2 台服务器，作者明确说明这是受控实验，与生产系统中 prefill/decode 角色通常共置的情况不同。
- 当前前缀缓存采用朴素的 LRU 淘汰策略，作者表示更复杂的替换策略留待未来工作。
- 由于 CXL Type-3 设备没有跨节点原子操作和全设备一致性，TraCT 依赖软件锁和 clflush 等显式 flush 机制，作者也指出 clflush 具有较高延迟。

证据：

- TraCT 的核心设计是让 GPU 通过 CXL load/store 与 DMA 直接读写 KV 块，从而消除现有解耦流水线中的 NIC 跳数。 — “TraCT enables GPUs to write and read KV blocks directly through CXL load/store and DMA operations, eliminating the NIC hop that constrains existing disaggregated pipelines.”，p. 1
- 该研究明确将 CXL 共享内存作为机架级 KV cache 和传输层，所有参与主机和 GPU 通过 load/store 与 DMA 直接访问，从而移除 KV 复用时的网络跳数，同时需要解决非一致 CXL 内存上的同步、一致性与数据管理挑战。 — “In contrast to network-centric designs, this study explores using CXL shared memory as a rack-scale KV cache and transfer layer directly accessible to all participating hosts and GPUs through load/store and DMA. This approach removes the network hop for KV reuse but raises new challenges such as synchronization, consistency, and data management on non-coherent CXL memory.”，p. 3

### P19 · Strata: Hierarchical Context Caching for Long Context Language Model Serving

Strata通过GPU辅助I/O与缓存感知调度，将碎片化的KV Cache加载与计算重叠，在长上下文服务中相比现有系统最高降低5倍TTFT并提升吞吐。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 性能评测与成本分析
- 研究问题：以vLLM为代表的AI Infra系统如何通过内存管理、请求调度、并行执行与软硬件协同提高大模型推理效率；具体聚焦于Strata如何将碎片化的KV Cache加载与计算重叠，降低长上下文服务的TTFT与I/O停顿。
- 方法：Strata包含两大核心组件：一是Strata Cache Controller，采用GPU-assisted I/O，通过启动CUDA kernel而非重复调用小尺寸cudaMemcpyAsync，用大量线程并发搬运小页数据，并支持在GPU计算友好的layer-first布局与host/disk传输友好的page-first布局之间进行近乎零开销的在线转换；二是Strata Scheduler，基于扩展SGLang RadixTree的HiRadixTree实现缓存感知调度，包括延迟命中请求的deferral、balanced batch formation（以loading_bound阈值平衡加载与计算），以及bubble filling（在不可避免的加载气泡中插入解码等有用计算）。系统基于SGLang实现并采用P-D co-location持续批处理。
- 实验设置：在H200平台（8×NVIDIA H200、PCIe 5.0 x16）和GH200 Grace-Hopper平台（H100+Grace CPU、464GB LPDDR5X）上评测；模型包括Llama-3.1-8B-Instruct、Qwen2.5-14B-Instruct-1M和Llama-3.1-70B-Instruct（70B使用4卡张量并行）；基线包括vLLM v0.8.5、vLLM-LMCache v0.2.1、TensorRT-LLM v0.17.0、TensorRT-HiCache以及实现层叠式KV Cache传输重叠的SGLang-HiCache；数据集使用LooGLE、NarrativeQA、ReviewMT和ShareGPT；请求到达采用Poisson分布，ShareGPT加入60秒思考时间，最大在途请求数为128，CPU端分配1TB pinned内存（GH200为400GB），所有基准中未使用磁盘存储。
- 与综述主题的关系：该论文属于AI Infra Systems中的KV Cache与内存管理、推理服务与请求调度方向。它直接回应了以vLLM为代表的长上下文服务瓶颈：PagedAttention等分页机制导致跨内存层级传输小块KV Cache时带宽利用率低，而调度器又未将I/O视为一等资源。Strata通过GPU-assisted I/O提升碎片化小页传输效率，并通过cache-aware scheduling将缓存加载与prefill/decode计算重叠，从而改善TTFT、吞吐与资源利用率；论文不涉及低精度计算、训练系统或分布式并行执行。
- 置信度：0.95

主要贡献：

- 提出Strata层次化上下文缓存框架，包含GPU辅助I/O与缓存感知调度两大设计。
- 设计GPU-assisted I/O内核，用少量大CUDA block将I/O限制在少量SM上，兼顾高带宽与低计算干扰，并解耦GPU与CPU/外部存储的KV Cache内存布局。
- 提出缓存感知调度：延迟命中请求延迟执行、形成平衡批次、用bubble filling隐藏I/O停顿，将CPU-GPU带宽作为一等资源。
- 基于SGLang实现并在生产环境部署；在长上下文基准上相对vLLM+LMCache最高5× TTFT降低、相对TensorRT-LLM最高3.75×加速，且不降低短上下文性能。

局限：

- 论文未设专门局限性章节；从文本可识别，GPU-assisted I/O内核仍有开销，作者计划未来进一步降低其开销。
- 评测中未使用磁盘缓存，原因是基线系统对磁盘支持有限，因此外部存储下的端到端效果未被充分评估。
- Strata聚焦于单计算实例内的内存管理和调度，未处理跨实例大规模KV Cache分池整合问题。

证据：

- Strata的核心思路是将GPU辅助I/O与缓存感知调度结合，从而把碎片化KV Cache加载与计算重叠。 — “Strata introduces GPU-assisted I/O to combat KV cache fragmentation, decoupling GPU and CPU memory layouts and employs cache-aware request scheduling to balance compute with I/O latency and overlapping unavoidable stalls with complementary tasks.”，p. 1
- 当批次仍处于加载受限时，Strata调度器通过向气泡中插入有用计算（如解码批次）来隐藏I/O停顿。 — “Finally, in the event that batches are still loading-bound, the Scheduler hides I/O stalls by inserting useful compute inside bubbles.”，p. 6

### P20 · AdaptCache: KV Cache Native Storage Hierarchy for Low-Delay and High-Quality Language Model Serving

AdaptCache提出一种面向DRAM/SSD分层存储的有损KV缓存压缩系统，通过为每个KV缓存条目自适应选择压缩算法、压缩率和设备放置，在保持生成质量的同时提高DRAM命中率并降低TTFT延迟。

- 分类：KV Cache与内存管理, 模型压缩与低精度计算, 推理服务与请求调度
- 研究问题：如何针对每个KV缓存条目自适应决定压缩算法、压缩率和设备放置，以在延迟与生成质量之间取得最优权衡？
- 方法：通过离线profiling估计每个条目、压缩方法和存储设备的质量-延迟曲线；定义效用函数 Utility(i) = Freq(i) * (alpha*Quality(i, Mi, Ri) - size(i, Mi, Ri)/Bandwidth)，并将优化建模为NP-hard的多选背包问题（MCKP）；采用基于边际效用下降的贪心策略，为新旧KV缓存条目选择压缩、驱逐或放置决策，由执行器实施。
- 实验设置：使用Llama-3.1-8B-Instruct模型，1,100个来自六个LongBench数据集的上下文，覆盖summarization、QA和coding三类任务；因数据集缺少时间戳，使用Poisson分布生成请求到达时间；实验运行在单块NVIDIA A100 GPU（100GB DRAM、400GB SSD）上，磁盘读取吞吐为1GB/s；对比无压缩offload、KIVI LRU、StreamingLLM LRU和Prefill等基线。
- 与综述主题的关系：该工作属于AI Infra Systems中的KV Cache与内存管理方向，通过有损压缩和自适应放置缓解LLM推理中的冗余计算与分层存储加载延迟问题；同时涉及推理请求调度中的TTFT优化以及模型压缩与低精度计算技术。
- 置信度：0.95

主要贡献：

- 提出AdaptCache，首个利用有损KV缓存压缩的分层KV缓存存储系统。
- 设计utility指标与边际效用下降贪心策略，联合决定压缩算法、压缩率和设备放置。
- 实验表明相比最强固定压缩基线，在相同质量下延迟降低1.43–2.4倍，在相同延迟下质量提高6–55%。

局限：

- AdaptCache采用贪心设计，并不保证最优，且论文指出最优解是NP-hard、不可追踪的。
- 当前论文标题为Preliminary Results，尚未给出大规模生产环境的全面部署评估。

证据：

- AdaptCache通过有损压缩KV缓存，使更多KV缓存条目能够放入CPU内存，从而在不显著降低生成质量的前提下提高高速设备命中率并降低加载延迟。 — “by lossily compressing the KV caches, we can store much more KV cache entries in CPU memory without significant degredation of generation quality”，p. 1
- 与最强固定压缩基线相比，AdaptCache在相同质量下实现1.43–2.4倍延迟降低，在相同延迟下实现6–55%质量提升。 — “Compared to the strongest fixed compression baseline, AdaptCache is 1.43–2.4× faster at the same quality and improves quality by 6–55% under the same delay.”，p. 2

### P21 · EVICPRESS: Joint KV-Cache Compression and Eviction for Efficient LLM Serving

EVICPRESS 提出按上下文粒度的统一效用函数，将跨存储层的 KV cache 驱逐决策与损失压缩决策联合优化，使系统在保持生成质量的同时降低 TTFT/延迟，并基于 vLLM 与 LMCache 实现验证。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 模型压缩与低精度计算, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度等提升大模型推理效率？具体而言，如何在多级存储（GPU/CPU/SSD）中联合优化每个上下文 KV cache 的压缩与驱逐，在质量约束下最小化平均生成延迟/TTFT并提高吞吐？
- 方法：EVICPRESS 将 KV cache 管理建模为每个上下文选择（存储层、压缩方法、压缩率）的配置问题，并用效用函数 Util(method,ratio,device)=(α·quality−TTFT)·frequency 统一量化每个配置对质量与延迟的影响；离线 profiler 基于每个上下文的一组问题计算所有配置的效用分数，在线阶段按新请求周期性重剖并更新配置；当存储层满时，将配置选择建模为多选背包（NP-hard）并用贪心算法以最小效用损失不断调整/驱逐，直到空间满足。实现基于 vLLM v0.11.2 与 LMCache，约 3K 行 Python/PyTorch 代码，通过拦截 LMCache 的 lookup/retrieve/store 并接入 vLLM 的 paged GPU 内存管理来编排 GPU/CPU/SSD 间的移动。
- 实验设置：评测使用 LongBench 12 个数据集、555 个上下文，每个上下文用 GPT-5 生成 100 条 QA（50 训练/50 测试）；硬件为单张 80GB H100 GPU、80GB CPU DRAM、800GB SSD，远程盘空间不限；模型包括 Llama-3.1-8B-Instruct、Qwen2.5-14B-Instruct、LongChat-7B、Mistral-7B-Instruct-v0.3 和 Qwen3-30B-A3B-Instruct-2507；基线与 Prefill、仅 LRU 驱逐、（keydiff/knorm/snapkv）压缩+LRU 驱逐、IMPRESS 对比；指标包括质量分数（MiniLM-L6-v2 余弦相似度）、TTFT、ITL、端到端延迟。
- 与综述主题的关系：该工作直接属于 LLM 推理系统中的 KV Cache 与内存管理，并通过请求调度（TTFT/QPS 优化）与损失压缩提升服务吞吐和成本效率，同时提供性能评测方法；其思想可被 vLLM 等 AI Infra 系统用于多级存储下的缓存决策。
- 置信度：0.95

主要贡献：

- 首个联合考虑损失压缩与跨层驱逐的多层 KV cache 管理系统 EVICPRESS。
- 提出统一效用函数，可比较所有可行的压缩-驱逐配置，明确优化目标。
- 在 vLLM 和 LMCache 上实现，并在多模型多数据集上验证 TTFT 与吞吐收益。

局限：

- 适用场景限于 GPU/CPU 内存有限的多级存储；若快存充足或各层带宽接近，联合优化收益会下降。
- 原型只在单节点 GPU 上评估，未扩展到多节点、跨 GPU 缓存共享、多租户隔离等场景。
- 假设各存储层带宽已知且相对稳定，带宽快速波动时预计算的效用分数可能暂时失配。
- 评测中压缩方法只包含三种 token dropping 方法，未纳入量化等更丰富方法。

证据：

- 论文主张，EVICPRESS 对所有上下文的 KV cache 统一考虑压缩和驱逐对平均生成质量与延迟的影响，而不是独立决策。 — “Specifically, for each KV cache of a context, EVICPRESSconsiders the effect of compression and eviction of the KV cache on the average generation quality and delay across all contexts as a whole.”，p. 1
- 论文报告，与统一压缩+LRU 驱逐基线相比，EVICPRESS 在相同质量分数下可将 TTFT 降低 1.43–3.77 倍。 — “EVICPRESSreduces TTFT by 1.43 to 3.77× at the same quality score”，p. 9

### P22 · VeriCache: Turning Lossy KV Cache into Lossless LLM Inference

VeriCache 提出将压缩 KV 缓存作为草稿生成器、以全量 KV 缓存进行验证的推理框架，在保持与全量 KV 解码完全相同输出的同时显著提升长上下文解码和远程前缀缓存吞吐。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：基于投机解码思想，用压缩 KV 缓存草稿 token，再用全量 KV 缓存并行验证并接受/纠正；提出跨资源交错调度（cross-resource staggering）将 HBM 带宽受限的草稿与互联带宽受限的验证重叠；引入统一压缩器接口，支持 token 丢弃和量化方法；运行时用带宽环和 HBM 环做资源建模与准入控制。
- 实验设置：在 Mistral-24B、Qwen-32B、Llama-70B 上评估；硬件包括 RTX PRO 6000 和 2×H100 NVL；Pipeline 1 为长上下文解码，Pipeline 2 为远程前缀缓存；压缩方法包括 KVzip、KVzap、ExpectedAttention、SnapKV、KIVI、KVQuant、RotateKV；基线包括 Full KV、EAGLE3 传统投机解码器、SparseSpec；数据集包括 LMCache-trace、ComplexFuncBench、PISanitizer、LongGenBench、GSM8K-Long，指标含 KL 散度、函数调用准确率、防御成功率、完成率和吞吐量。
- 与综述主题的关系：该工作属于 KV Cache 与内存管理、推理服务与请求调度以及性能评测交叉方向：通过把有损压缩作为草稿、全量 KV 作为验证，在不损失输出正确性的前提下利用压缩带来的 HBM/互联带宽收益，提高 LLM 在线推理吞吐和可靠性。
- 置信度：0.95

主要贡献：

- 首个通过压缩 KV 草稿 + 全量 KV 验证保证与 full-KV 解码输出相同的推理框架。
- 跨资源交错调度设计，将草稿与验证阶段在 HBM/互联/算力上重叠。
- 统一压缩器接口，实例化七种 token-dropping 和量化方法。
- 同时支持长上下文解码和远程前缀缓存，并可与传统投机解码组合。

局限：

- 需要在 CPU/存储上保留全量 KV，增加存储开销。
- 固定草稿长度，缺少逐请求自适应策略。
- 现有压缩器面向直接服务准确率优化，而非最大化长草稿接受长度。
- 尚未扩展到压缩之外的其他 lossy KV 技术（如跨非前缀块复用预计算 KV）。

证据：

- VeriCache 的核心机制是用压缩 KV 缓存草稿 token，再用全量 KV 缓存验证，从而保证输出与 full-KV 解码一致。 — “VeriCache uses the compressed KV cache to draft tokens, then verifies them against the full KV cache.”，p. 1
- 实验显示 VeriCache 在保持输出一致的前提下，可获得最高 4 倍于 full-KV 推理的吞吐。 — “Experimental results show that VeriCache achieves up to4× higher throughput than full-KV inference while producing identical outputs.”，p. 1

### P23 · OrbitFlow: SLO-Aware Long-Context LLM Serving with Fine-Grained KV Cache Reconfiguration

OrbitFlow通过轻量级ILP求解器为每个请求按层动态决定KV cache在GPU/CPU间的放置，并配合Token-Deposit与Pause-Resume，在长上下文LLM推理中提升SLO达成率与吞吐。

- 分类：KV Cache与内存管理, 推理服务与请求调度
- 研究问题：在线ILP放置如何适应不断变化的KV cache内存需求？
- 方法：OrbitFlow采用闭环控制：Runtime Executor执行每个decode步骤并记录计算时间、传输时间和GPU内存用量；Adaptive Controller根据profile偏差触发和batch变化触发判断当前放置是否失效，并在必要时启动Pause-Resume fallback；Placement Planner使用经过搜索空间剪枝的ILP求解器，为每个请求独立选择距离驱动的层级offload距离，并通过decode window控制求解频率；求解器提前一个decode step在独立线程运行以隐藏开销。分布式场景下在tensor parallelism的一个worker上求解并广播放置。
- 实验设置：默认配置为LLaMA3-8B在单张NVIDIA RTX A5000 (24GB) GPU上运行，主机内存384GB，PCIe 3.0 x16；长上下文实验使用LLaMA3-70B在4张RTX A6000 (48GB) GPU节点上运行。工作负载基于ShareGPT采样合成，使用Poisson到达率模拟在线服务。基线包括DeepSpeed-Inference、FlexGen、FlexGen+、SLO-aware Offloading和Dynamic Heuristic。评估指标包括TBT和TPOT SLO达成率、P95/P99时延、端到端时延、吞吐量和GPU内存利用率。
- 与综述主题的关系：该论文属于AI Infra Systems中的KV Cache与内存管理以及推理服务与请求调度方向，核心贡献是用在线ILP优化request-level KV cache放置，以应对长上下文推理中token维度和batch维度导致的内存需求动态变化，从而提高SLO达成率、降低尾部时延并提升吞吐。
- 置信度：0.95

主要贡献：

- 提出OrbitFlow，实现请求级细粒度KV cache放置，每个请求可以选择不同的层间offload距离。
- 设计轻量级ILP求解器，在GPU容量、SLO违规上限和decode window约束下最小化batch级decode延迟。
- 引入动态重配置机制，通过profile-mismatch和batch-change触发器随KV cache增长和batch组成变化持续更新放置。
- 提出Token-Deposit和Pause-Resume两种fallback机制，在过载时通过缓冲输出和暂停大内存footprint请求保障整体SLO。
- 在vLLM上实现并验证，支持tensor parallelism扩展到单节点多GPU场景。

局限：

- OrbitFlow当前仅扩展至单节点多GPU的tensor parallelism，跨节点pipeline parallelism和数据并行场景留作未来工作。
- 在服务器严重过载时OrbitFlow仍可能无法满足所有SLO，Pause-Resume只能缓解瞬时过载而不是提供严格保证。
- 搜索空间剪枝会跳过非均匀间隔的层数组合，约16.7%的Full解严格更优，尽管中位改善较小且完整搜索开销过高。
- Pause-Resume会延迟被暂停请求的完成时间，使端到端时延比自适应基线高12-21%。

证据：

- OrbitFlow的核心是一个轻量级ILP求解器，动态优化批处理请求之间的GPU内存使用，以最小化SLO违规。 — “OrbitFlowemploys a lightweight ILP-based solver that dynamically optimizes GPU memory usage across batched requests to minimize SLO violations.”，p. 2
- 解码早期的最优KV放置会随着KV cache增长而变得次优甚至不可行，因此需要动态重配置。 — “A placement that was optimal early in decoding can later become suboptimal—or even infeasible—as KV caches grow. A single, static placement therefore cannot serve all decode steps;dynamic reconfigurationis required.”，p. 4

### P24 · vToken: Token-Level Virtualization for Reclaimable KV Caches

vToken 在 PagedAttention 的块管理 KV 缓存之上引入 token 级虚拟化层，通过 token-table 间接寻址将逻辑 token 活跃性与物理块放置解耦，并借助异步重打包回收块内碎片，从而在不修改注意力内核的前提下提升 KV 内存可回收性与推理吞吐。

- 分类：KV Cache与内存管理, 推理服务与请求调度, 性能评测与成本分析
- 研究问题：token-table 间接层如何将逻辑 token 活跃性与物理块放置解耦，从而在不改动 PagedAttention 内核的前提下回收 token 级驱逐策略造成的块内碎片？
- 方法：基于 PagedAttention 块管理运行时设计 token 级虚拟化边界：每请求维护 token table，记录逻辑 token ID 到 (block, offset) 的映射及 liveness 位；向上对驱逐策略暴露 evict_token、sync_new_tokens 等块无关接口，向下由物理回收后端通过 lazy compaction 将低利用率块中的存活 token 重打包，并异步更新 token table 与 attention slot 映射；使用 CUDA event 建立 pre-attention 依赖以保证重定位后的 KV 可见性，同时保持 CUDA Graph 兼容。实现于 vLLM v0.18.0 之上，包含 TokenTable、ReclamationManager 和 CUDACopyEngine 三个组件。
- 实验设置：单块 NVIDIA H100 80GB；主实验使用 Mistral-7B 与 Llama-3.1-8B，在 ShareGPT 和 LongBench 上评估，额外用 Qwen2.5-14B 做容量前沿验证；策略包括 H2O、Scissorhands、Random；对照基线为 Native vLLM（全保留）和 Naive-Evict（相同驱逐决策但禁用 vToken 物理回收）；配对对比使用相同提示、模型、策略与内存预算，默认 gpu_mem_util=0.90，容量前沿实验使用受控 KV 预算；所有报告实验启用 CUDA Graph。
- 与综述主题的关系：该工作属于 AI Infra 系统中的 KV Cache 与内存管理方向：vToken 通过 token 级虚拟化与异步重打包解决 token 级驱逐和块级管理之间的粒度失配，将逻辑活跃性转化为可回收的物理 KV 容量，从而提升在线推理的并发能力、SLA 约束吞吐与内存利用率，同时保持 PagedAttention 内核和 CUDA Graph 兼容，是 vLLM 类推理系统内存管理优化的重要示例。
- 置信度：0.93

主要贡献：

- 识别出 token 级 KV 驱逐与块级 KV 缓存管理之间的粒度失配是一个缺失的运行时抽象层，并通过初步实验量化了其内存代价
- 提出 vToken，一个 token 级虚拟化层，通过 token-table 间接寻址将逻辑 token 活跃性与物理块放置解耦，无需修改注意力内核即可提供稳定的每序列 token 视图和物理回收能力
- 在 vLLM 中实现 vToken，并跨模型与三种驱逐策略验证其效果：相比 Naive-Evict 减少保留 KV 块 27.2%–72.3%，SLA 约束吞吐最高提升 1.37×，受约束 active-KV 预算下最大可行并发最高扩展 2×，每策略集成代码从 500+ 行降至 50 行以内

局限：

- 当前原型只面向单节点、单 GPU 的 decoding fast path，未涉及分布式调度或跨设备 KV 移动
- 当前实现仅使用一个 runtime KV cache group，并保守地跳过共享前缀块以保持 prefix-cache 正确性
- 异步拷贝虽避免显式同步停顿，但仍可能与 decode 竞争 HBM 带宽；planner 侧机会检查的开销是主要测量成本
- vLLM 版本要求 block size 至少为 16 tokens，因此 block-size 扫描受限，无法在更小块大小下评估
- 容量前沿与重定位效果的敏感性依赖于驱逐比例和碎片阈值，论文未将 vToken 与 KV 量化/混合精度等表示层优化结合评估

证据：

- vToken 通过 token-table 间接层维持稳定的逻辑 token 视图，并以异步重打包存活 token 的方式实现物理回收，从而将逻辑 liveness 与物理块放置解耦。 — “maintains a stable logical token view through token-table indirection and realizes physical reclamation by repacking live tokens asynchronously.”，p. 1
- 标记 token 可回收只更新 token table 元数据，物理 KV 内存不会立即移动或释放；这种间接寻址把策略语义（驱逐什么）与物理布局维护（如何重打包存活 token）分离。 — “Marking a token reclaimable updates only this metadata; no KV memory is moved or freed until the reclamation backend acts. This indirection separates policy semantics (what to evict) from physical layout maintenance (how to repack live tokens).”，p. 4

### P25 · MiniKV: Pushing the Limits of LLM Inference via 2-Bit Layer-Discriminative KV Cache

MiniKV通过将2-bit KV缓存量化与金字塔逐层KV预算分配及FlashAttention兼容的两遍注意力内核协同设计，在长上下文任务上实现约86%的KV缓存压缩并保持与全模型接近的准确率。

- 分类：KV Cache与内存管理, 模型压缩与低精度计算, 异构硬件与内核优化, 性能评测与成本分析
- 研究问题：How should 2-bit KV cache quantization techniques be combined with adaptive KV policies to maximize the inference speed of LLMs given a memory budget while retaining high model accuracy in long context inference?
- 方法：论文采用算法与系统协同设计：算法侧将2-bit KV缓存量化（子通道Key量化和per-token Value量化）与自适应KV策略结合，比较uniform、variance-based和Pyramid逐层KV预算分配并选择Pyramid策略；系统侧设计两遍Triton选择性FlashAttention内核，以线性内存输出累积注意力分数Acumul，解决score-based淘汰策略与FlashAttention的不兼容问题，并开发解码阶段的融合解量化与矩阵乘法内核。
- 实验设置：在LLaMA2-7B-chat、LLaMA2-13B-chat和Mistral-7B-Instruct-v0.2上，使用LongBench（13个数据集）、InfiniteBench和GSM8K评估；硬件为NVIDIA A100-40GB、A40-46GB和GH200-120GB GPU；MiniKV采用50%缓存预算（25% heavy hitter + 25% recent window），量化group size为16，残差长度nr=128；对比基線包括H2O、SnapKV、KIVI、Q-Hitter和FullKV。
- 与综述主题的关系：该项工作属于KV Cache与内存管理、模型压缩与低精度计算，以及异构硬件与内核优化的交叉：通过2-bit低精度KV缓存和逐层自适应内存分配降低显存占用，并通过自定义Triton/FlashAttention兼容内核提升长上下文推理的延迟和吞吐，直接支撑以vLLM为代表的AI Infra系统在推理服务中的成本与效率优化。
- 置信度：0.92

主要贡献：

- 提出MiniKV，将2-bit KV量化与自适应KV策略协同组合，在长上下文任务中实现约86%的KV缓存压缩并保持可比较准确率。
- 发现Pyramid逐层KV缓存分配在中等淘汰率下显著优于uniform和variance-based分配，用于保持长上下文准确率。
- 设计两遍Triton选择性FlashAttention内核，以线性内存复杂度输出累积注意力分数，解决score-based淘汰与FlashAttention的不兼容。
- 开发解码阶段融合解量化与矩阵乘法的内核，降低延迟并提高吞吐。

局限：

- 论文主要聚焦KV缓存优化，尚未与模型压缩等其他优化技术组合。
- 尝试组合SnapKV与KIVI时LongBench分数从35降到32，表明不同淘汰策略选中的token对2-bit量化的敏感度不同，需要更鲁棒的组合框架。

证据：

- Pyramid逐层KV缓存分配策略在中等淘汰率下比其他逐层策略准确率更高，说明逐层差异化分配缓存预算有助于保持长上下文准确率。 — “In our experiments, we observe that the Pyramid policy achieves much better accuracy than the other policies, especially with medium levels of eviction, shown in Fig. 3.”，p. 5
- 在相同KV缓存大小条件下，MiniKV-Pyramid在LLaMA2-7B-chat上达到全模型准确率的98.5%，表明逐层金字塔分配与2-bit量化结合能保留长上下文准确率。 — “an average accuracy of 34.65, obtaining 98.5% of the full model accuracy 35.19.”，p. 7

### P26 · Oaken: Fast and Efficient LLM Serving with Online-Offline Hybrid KV Cache Quantization

Oaken 提出在线-离线混合 KV Cache 量化算法与定制量化/反量化引擎、内存管理单元，通过离线确定异常值阈值、在线计算量化 scale，以软硬件协同设计提升 LLM 在线推理吞吐并保持较低精度损失。

- 分类：推理服务与请求调度, KV Cache与内存管理, 模型压缩与低精度计算, 异构硬件与内核优化, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：Oaken 采用算法-硬件协同设计：(1) 离线 profiling 通过约百次采样推理、用 topK 统计每个 decoder layer 的组阈值，在线仅用这些阈值将 per-token KV 划分为 outer/middle/inner 三组并动态计算每组 min/max 得到均匀量化 scale；(2) 提出 group-shift quantization，将 outer/middle 组整体平移以收窄数值范围，使 4/5-bit 量化可行；(3) 提出 fused dense-and-sparse encoding，将稀疏 outlier 的 4 bit 嵌入 dense 矩阵的零元素，使 outlier 条目从 23 bit 降至 8 bit；(4) 在 DMA 中实现量化/反量化引擎和双管理表 MMU，以页粒度管理 dense/sparse KV cache，并通过 token 级批量调度将量化/反量化与 DMA 读取和注意力计算重叠以隐藏开销。
- 实验设置：基于 LPU 模拟器扩展搭建 Oaken 加速器，并用 SystemVerilog RTL 在 TSMC 28nm 综合验证；评测 8 个 LLM（Llama2-7B/13B/70B、OPT-6.7B/13B/30B、Mistral-7B、Mixtral-8x7B）；使用 Wikitext2、PIQA、Winogrande、Hellaswag 数据集以及 Azure Conversation 和 BurstGPT 真实 trace；GPU 基线包括 vLLM、QServe、KIVI、KVQuant，ASIC 基线包括 Tender，另有 Atom 参与精度对比；批量大小从 16 到 256，总序列长度从 1K 到 32K；对比平台为 NVIDIA A100 GPU 与配置 HBM/LPDDR 的 Oaken 加速器。
- 与综述主题的关系：该论文直接回应 AI Infra 系统中低精度计算、内存管理与软硬件协同如何提升在线推理吞吐的问题：Oaken 将 KV cache 量化的关键决策（异常值阈值）移到离线阶段，在线只做轻量统计与均匀量化，从而避免了现有 KV 量化方案中在线 outlier 检测/排序的高开销；同时用定制 DMA 量化/反量化引擎和 MMU 将这些算法收益转化为实际带宽与容量提升。实验表明在 batch=256 时相对 A100 GPU 上的 SOTA KV 量化方案 QServe 有 1.58× 吞吐提升，展示了离线阈值设置为高性能在线 KV 量化铺平道路的核心价值。
- 置信度：0.95

主要贡献：

- 提出 online-offline 混合 KV cache 量化：离线确定数据无关的异常值阈值，在线仅据此设置量化 scale，避免在线 topK/排序和混合精度计算的过高开销。
- 提出 group-shift quantization：利用离线阈值将 outer/middle 组整体平移收窄分布，使宽范围异常值也能用低 bit 量化。
- 提出 fused dense-and-sparse encoding：复用 dense 矩阵中的零元素存储部分 outlier 位，将每个 outlier 条目的存储成本从 23 bit 压缩到 8 bit。
- 设计可集成到任意 LLM 加速器的量化/反量化引擎与双管理表 MMU，以页粒度管理 dense/sparse KV cache，最大化带宽利用并避免碎片化。
- 在 LPU 上实现 Oaken 加速器，验证其在吞吐、准确率、面积与功耗方面的综合优势。

局限：

- 当总序列长度低于 8K 时，计算密集、可 batch 的操作占比更高，QServe 和 vLLM 在 GPU 上的吞吐可超过 Oaken。
- 对于使用 grouped-query attention 的 Mixtral-8x7B 等模型，KV cache 本身较小，量化基线（包括 Oaken-LPDDR）在部分真实 trace 下相对全精度基线几乎没有性能增益。
- Oaken-HBM 在 Mixtral-8x7B 和 Llama2-70B 等大模型或大批次场景下受限于内存容量，难以完成整个 batch。

证据：

- Oaken 通过离线确定数据无关的 outlier 阈值、在线仅用这些阈值设置量化 scale，从而避免在线高开销的异常值检测。 — “To achieve this goal, Oaken employs an online-offline hybrid approach, where data-agnostic outlier thresholds are determined at offline and subsequently applied to set the quantization scale at online.”，p. 2
- 离线 profiling 只需约一百次推理且仅需执行一次，对 Llama2-70B 也仅约十分钟，因此在线 KV 量化的额外开销可忽略。 — “Oaken’s offline profiling requires only about a hundred inferences and takes approximately ten minutes, even for the Llama2-70B model. Since this process is required only once before serving LLM inference online, the overhead is negligible.”，p. 10

### P27 · Queue management for slo-oriented large language model serving

QLM 是一个面向 SLO 的 LLM 服务队列管理系统，通过请求等待时间（RWT）估计器预测请求在队列中的等待时间，并由全局调度器据此执行请求拉取、请求驱逐、负载均衡和模型切换，从而在 vLLM 等后端上提升 SLO 达成率与吞吐量。

- 分类：推理服务与请求调度, 性能评测与成本分析
- 研究问题：如何通过估计请求等待时间驱动请求拉取、请求驱逐和负载均衡等队列管理操作，以在面向 SLO 的 LLM 服务中最大化 SLO 达成率并提高资源利用率？
- 方法：QLM 将请求按模型、SLO 和 token 分布聚类为请求组（request groups），并映射到与 LLM 服务实例一一对应的虚拟队列（virtual queues）。RWT 估计器基于输出 token 数分布和 token 生成吞吐量，利用中心极限定理给出请求组等待时间的解析估计。全局调度器以线性规划求解请求组到虚拟队列位置的分配，最小化 SLO 违规惩罚，并将虚拟队列顺序转换为四种 LLM 服务操作（LSO）：请求拉取、请求驱逐、模型切换和负载均衡。实验在 vLLM 上实现并与 EDF、vLLM 默认调度和 SHEPHERD 对比。
- 实验设置：使用 Mistral-7B、Vicuna-13B 和 Llama-70B 三个开源 LLM，测试床包含 30 张 NVIDIA A10（24GB）和 50 张 NVIDIA A100（80GB）GPU。工作负载基于 ShareGPT 数据集，每个 trace 使用 3,500 个请求，请求到达率用泊松分布建模；SLO 按 TTFT p99 设为三类：Interactive 20s、Batch-1 1min、Batch-2 1hour。对比基线包括 EDF、vLLM 和 SHEPHERD，并包含单模型混合负载（WA）、多模型批量负载（WB）和单模型 MegaPrompt 负载（WC）三种场景。
- 与综述主题的关系：本文聚焦 AI Infra 中的推理服务与请求调度：通过请求等待时间估计驱动全局队列排序，进而控制请求拉取、驱逐、负载均衡和模型切换，以提升 vLLM 等 LLM serving 系统的 SLO 达成率、吞吐量和设备利用率，属于请求调度与队列管理方向的核心工作。
- 置信度：0.95

主要贡献：

- 提出 QLM，一个面向 SLO 的 LLM 服务队列管理框架，能够编排请求拉取、请求驱逐、负载均衡和模型切换等 LSO。
- 设计 RWT 估计器，利用连续批处理下的统计平均效应和中心极限定理解析估计请求等待时间。
- 引入请求组和虚拟队列抽象，将调度决策从单请求粒度提升到请求组粒度，降低优化开销并支持多模型场景。
- 实现基于线性规划的全局调度器，将请求组排序并映射到虚拟队列，以最大化 SLO 达成率。
- 在 vLLM 上实现 QLM 并开源，且已合入内部生产 LLM 路由服务。

局限：

- 当请求组数量较少时，RWT 估计器会高估等待时间，导致系统相对最优情况可能利用不足。
- 当输出 token 数超出分布范围（如高于均值 5–10 个标准差）时，估计器可能低估完成时间，造成 SLO 违规。
- QLM 主要针对 TTFT SLO，不保证 inter-token latency（ITL），需要与其他系统如 Andes 配合。
- QLM 不实现抢占式负载均衡，请求组开始执行后不能迁移到其他实例。
- 多模型交互式负载中，由于模型切换时间超过 20s SLO，QLM 会为每个模型分配独立 GPU，不做模型切换。
- 请求驱逐和模型切换需要较大的 CPU 内存：Vicuna-13B/Mistral-7B 需额外 80GB，Llama-70B 需额外 320GB。

证据：

- QLM 使用 RWT 估计器估计请求队列中的等待时间，这些估计由全局调度器用于编排请求拉取、请求驱逐、负载均衡和模型切换等 LLM 服务操作。 — “To generate this optimal ordering, QLM uses a Request Waiting Time (RWT) Estimator that estimates the waiting times for requests in the request queue. These estimates are used by a global scheduler to orchestrate LLM Serving Operations (LSOs) such as request pulling, request eviction, load balancing, and model swapping.”，p. 1
- 请求驱逐由 RWT 估计器检测到 SLO 违规时触发，全局调度器将某个请求组放到虚拟队列头部以替换原有请求组。 — “Request eviction is invoked when the RWT estimator detects an SLO violation, and the global scheduler replaces an existing request group by placing a request group at the head of the virtual queue.”，p. 7

### P28 · ServeGen: Workload Characterization and Generation of Large Language Model Serving in Production

本文通过对阿里巴巴云 Model Studio 生产环境中海量 LLM 服务工作负载（覆盖语言、多模态和推理模型）进行特征刻画，提出按客户端组合生成真实工作负载的 ServeGen 框架，以提升推理系统基准测试的真实性。

- 分类：性能评测与成本分析, 推理服务与请求调度
- 研究问题：多模态模型和推理模型的新工作负载特征如何影响 LLM 服务？
- 方法：对生产集群中 12 个模型、数十亿条请求（跨越四个月）的日志进行特征分析，包括到达模式、输入/输出长度分布、多模态输入构成、推理模型的推理/回答长度等，并通过客户端分解解释整体负载规律；基于这些发现，以 per-client 方式建模并生成合成工作负载，使用 vLLM 和 SGLang 等系统进行基准对比。
- 实验设置：数据来自阿里巴巴云 Model Studio，覆盖语言、多模态、推理三类共 12 个模型；用于验证的系统包括 vLLM（Qwen2.5-14B，2×A100 实例）和 PD-disaggregated SGLang（Qwen2.5-72B，4 节点各 8 张 H20 GPU）；对比基线为 NAIVE 工作负载生成方法。
- 与综述主题的关系：论文聚焦在线推理服务的工作负载特征与生成，直接服务于 LLM serving 系统的性能评测、容量规划、请求调度和架构优化（如 PD 分离），为内存管理、调度策略等 AI Infra 优化提供现实依据。
- 置信度：0.95

主要贡献：

- 提供了覆盖语言、多模态和推理模型的大规模生产级 LLM 服务工作负载特征研究。
- 通过按客户端分解揭示了真实工作负载的因果建模规律（少数头部客户导致整体波动）。
- 开源了 ServeGen 工作负载生成框架，支持更真实的基准测试。

局限：

- 未覆盖插件调用（plugin calls）场景。
- 出于保密义务未分析前缀缓存（prefix caching）。
- 单个工作负载的时间跨度不足以进行长期纵向研究。

证据：

- 多模态请求在输入构成上高度异构，且预处理阶段的开销会显著延长 TTFT。 — “Finding 7: Multimodal requests are heterogeneous with diverse ratios of multimodal inputs per request, leading to prolonged TTFTs that require tailored optimizations.”，p. 7
- 推理模型输出因推理 token 而更长且更不稳定，推理与答案长度呈现双峰比例。 — “Finding 9: Reasoning workloads exhibit longer and more variable output lengths, due to the reason tokens.”，p. 8

### P29 · Attention to Detail: Evaluating Energy, Performance, and Accuracy Trade-offs Across vLLM Configurations

本文通过 9,000 次受控运行系统评估了 vLLM 的注意力内核、前缀缓存与分块预填配置在 5 个 LLM 和 5 类任务上对能耗、延迟和准确率的交互影响，发现配置效果高度依赖模型与任务，模型选择主导全局权衡，且推理配置可意外影响模型准确率。

- 分类：推理服务与请求调度, KV Cache与内存管理, 异构硬件与内核优化, 性能评测与成本分析
- 研究问题：在给定 LLM 和任务类型下，vLLM 配置选项及其交互如何影响能耗、性能和准确率？vLLM 配置与任务类型之间存在哪些交互效应？在给定任务类型下，哪些 vLLM 配置能在能耗、性能和准确率之间达到帕累托最优？
- 方法：遵循实证软件工程与能耗测量指南的受控因子实验；使用全因子设计，组合 3 种注意力内核、2 个前缀缓存设置、2 个分块预填设置、5 个 LLM 与 5 个任务数据集，每个配置重复 30 次，共 9,000 次运行并收集 93,600 个数据点；采用 ART ANOVA（Aligned Rank Transform）进行非参数假设检验、Holm-Bonferroni 校正、Cliff's Delta 效应量估计，以及帕累托前沿分析回答三个研究问题。
- 实验设置：5 个开放权重 LLM：Qwen3-32B、Qwen3-4B、Magistral-Small-2509（24B）、Llama-3.1-8B-Instruct、Llama-3.2-3B-Instruct；5 个任务数据集：AssistantTraces、EvoEval、LongBench-v2、Natural Questions、WildChat；3 种注意力内核 FlashAttention-2、FlashAttention-3、FlashInfer，前缀缓存与分块预填各开/关；运行于 4 台相同节点（AMD EPYC 7513、512 GiB 内存、4×Nvidia A100-SXM4-40GB），使用 vLLM 0.10.2、FlashInfer 0.4.1、CUDA 12.2.128；推理参数 temperature=0.4、top-p=0.95、max-tokens=2048，其余保持默认；能量通过 nvidia-smi 和 perf 以 1Hz 采样并按 E=W×T 计算。
- 与综述主题的关系：该论文属于 AI Infra Systems 的性能评测方向，针对 vLLM 这一代表性推理引擎，系统评估注意力内核、前缀缓存（KV Cache 复用）和分块预填（prefill 调度）三类系统级配置对能耗、TTFT/请求延迟和输出准确率的交互影响；其结果直接服务于推理服务配置优化、KV Cache 内存管理策略选择与异构 GPU 内核选型，为理解 vLLM 配置空间对延迟、成本效率与可靠性的影响提供实证基础。
- 置信度：0.95

主要贡献：

- 提供实证证据表明所选 vLLM 配置选项影响推理能耗与性能，且效应依赖任务类型
- 发现注意力类型与前缀缓存等配置选项存在交互，单个选项的影响不能孤立评估
- 证明模型选择主导能耗-延迟-准确率帕累托前沿，配置调优仅提供局部优化
- 揭示推理配置可能意外影响模型准确率，挑战其纯粹属于系统级优化的假设
- 发布完整复制包以支持可复现性与后续研究

局限：

- 实验仅使用 NVIDIA A100-SXM4-40GB GPU；例如 FlashAttention-3 针对 H100 调优，结果可能无法推广到其他硬件平台
- nvidia-smi 在 A100 上仅采样 25% 运行时间的功率，其余插值，在非常尖峰的工作负载下能耗误差可达 65%，能耗值应视为估计值
- 准确率仅在 EvoEval 和 LongBench 上评估，因为 AT、WC、NQ 缺少可靠真值；采样解码下准确率差异也可能部分反映随机生成效应
- 使用 vLLM 0.10.2 的离线批处理接口而非 HTTP 服务器模式，异步请求、调度与缓存行为可能不同；结论仅针对 vLLM，其他推理引擎可能不同
- 仅评估三个配置选项且其余参数保持默认；vLLM 默认设置下启用 chunked prefill 并不一定会为短提示任务触发分块机制
- 模型家族、规模、数据集和版本只覆盖部分设计空间，外部有效性有限；未来需扩展到其他 vLLM 参数、硬件、多 GPU 部署和 MoE 架构

证据：

- 所研究的 vLLM 配置选项显著影响能耗和性能，主要由注意力类型和前缀缓存驱动；在所采用的默认 vLLM 配置与负载下分块预填影响有限。 — “Our results show that the studied configuration options significantly impact energy and performance, mainly driven by attention type and prefix caching, while chunked prefill has a limited effect under the default vLLM serving configuration and evaluated workloads.”，p. 1
- 注意力类型与前缀缓存存在交互效应；例如前缀缓存带来的延迟收益取决于使用的注意力后端，因此不能孤立评估单个配置选项。 — “the latency gain from prefix caching depends on the attention backend in use”，p. 2

### P30 · Continuous Discovery of Vulnerabilities in LLM Serving Systems with Fuzzing

GRIEF 是一种面向 LLM 推理引擎的灰盒模糊测试工具，将带时间的多请求轨迹作为输入，通过行为、结构与关系预言机及受控重放，在 vLLM 和 SGLang 中发现 15 个漏洞（10 个开发者确认、含 2 个 CVE），涵盖 KV 缓存隔离失效、跨请求性能干扰与崩溃/存活问题。

- 分类：推理服务与请求调度, KV Cache与内存管理, 可靠性、弹性与可观测性
- 研究问题：带时间的多请求轨迹如何揭示 LLM 服务层的可靠性与安全缺陷？
- 方法：GRIEF 将并发客户端工作负载建模为时间戳化的请求轨迹，使用时序、事件、拼接三类变异探索请求重叠、前缀缓存复用、适配器共调度与取消时机；采用行为预言机、结构预言机（KV-cache 事件）和关系预言机（logprob 辅助重放），并通过受控重放与多数投票确认可复现的服务层故障。
- 实验设置：在 vLLM 与 SGLang 上各运行 8 小时并发模糊测试，使用 Qwen2.5-0.5B-Instruct 和 H100 GPU；状态破坏实验使用 Qwen3-8B 与 GSM8K/GSM8K-hard，对每个受害提示在 solo、benign-concurrent、attack-concurrent 三种条件下各 10 次重复；性能干扰实验维护 8 个并发受害客户端并测量 TTFT 与吞吐量；SGLang LoRA 崩溃实验在单块 H100 上约 200 次迭代内触发崩溃。
- 与综述主题的关系：本文直接展示 vLLM/SGLang 等推理服务系统中，内存管理（KV cache）与请求调度（并发批处理、适配器调度、前缀共享）的工程决策会引入服务层安全/可靠性漏洞；GRIEF 以带时间请求轨迹为模糊输入，证明这些缺陷只有在并发负载下才会暴露，是 AI Infra 系统吞吐、延迟、成本与可靠性研究中不可忽略的测试维度。
- 置信度：0.95

主要贡献：

- 将并发 LLM 推理服务定义为安全相关攻击面，表明合法请求可触发隔离、性能与存活失败。
- 提出 GRIEF，以带时间多请求轨迹为输入的灰盒模糊测试器，支持时序、事件、拼接变异及定向拼接。
- 设计分层预言机与确认管线，包括行为检查、logprob 辅助关系确认和 KV 结构取证。
- 在 vLLM 和 SGLang 上评估，发现 15 个潜在漏洞、10 个开发者确认，包括 2 个 CVE。

局限：

- 当前评估集中于 vLLM 和 SGLang 及代表性服务模式与硬件，其他引擎、分布式部署、硬件后端或模型架构可能需要额外适配器与遥测钩子。
- GRIEF 不能证明没有 bug，其效果依赖种子、变异、反馈信号和模糊测试预算。
- 最强的结构预言机依赖引擎级可观测性，确认策略保守，可能漏报部分低置信度候选。
- 案例研究刻画的是已确认 bug 的代表性后果，而非对所有生产部署的利用性建模，实际严重性取决于租户隔离、批处理策略、限流、监控和恢复机制。

证据：

- GRIEF 的核心抽象是带时间戳的请求轨迹，同时编码请求内容、请求重叠方式以及对共享服务状态的竞争，从而能够发现仅由并发工作负载结构触发的服务层缺陷。 — “Its core abstraction is a timedrequest trace: a sequence of events that captures not only what clients ask, but when requests overlap and how they compete for shared serving state.”，p. 2
- 单个 API 合法的攻击者请求形状可以导致无关租户的跨请求饥饿，造成严重延迟放大和吞吐量塌缩，而服务器不崩溃、不返回显式错误。 — “Thus, a single attacker client repeatedly issuing one API-valid request shape, using documented and permitted parameters with no malformed input, can induce cross-request starvation in a shared inference server.”，p. 8

### P31 · Deterministic Inference across Tensor Parallel Sizes That Eliminates Training-Inference Mismatch

本文提出 Tree-Based Invariant Kernels (TBIK)，通过固定二叉树归约顺序同时约束 GPU 内 MatMul 与 GPU 间 All-Reduce，实现跨不同张量并行大小的逐位确定性推理，并消除 RL 管线中 vLLM 与 FSDP 之间的概率失配。

- 分类：并行计算与分布式执行, 推理服务与请求调度, 可靠性、弹性与可观测性
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？子问题：层次化归约顺序如何确保跨 TP 配置的确定性？
- 方法：提出 Tree-Based Invariant Kernels (TBIK)：为 intra-GPU MatMul 和 inter-GPU All-Reduce 设计统一的固定全二叉树归约拓扑；每个 partial MatMul 结果对应叶子节点，内部节点按确定顺序两两累加，使全局累积顺序与 TP 大小无关。局部核用 Triton 实现，采用深度 L=log2(TK/C) 的 accumulator buffer 和 counter carry-over 机制；同时实现自定义 tree all-reduce，节点内也严格按二叉树结构归约。集成到 vLLM 与 FSDP：column-parallel 层使用 BIO，row-parallel 层使用 Tree-Based MatMul，并统一 attention、RMSNorm、RoPE、SiLU 等 kernel，且禁用 chunked prefill。
- 实验设置：在 vLLM 后端、eager mode、固定随机种子下评估 Qwen3-8B、Qwen3-32B、Mistral-7B-Instruct-v0.3、Llama-3.1-8B-Instruct 在 AIME24 和 AMC23 上的可复现性；覆盖 TP=1/2/4/8（Qwen3-32B 为 2/4/8）与 BS=8/16/32 的 12/9 种运行时配置，并在 NVIDIA RTX PRO 6000 和 L40S 上重复；对比 BF16、仅 BIO、BIO+TBIK；指标包括 Unique Outputs 数、最大概率散度、端到端延迟。RL 实验使用 GRPO 在 GSM8K 上以 Qwen3-1.7B 在 4×L40S 上进行，vLLM 以 TP=4 做 rollout，FSDP 以 TP=1 做训练。
- 与综述主题的关系：该工作属于 AI Infra 系统中并行计算与分布式执行、推理服务可靠性方向：通过软硬件协同设计（Triton kernel 加自定义 All-Reduce）在 vLLM/FSDP 中消除张量并行规模变化引起的浮点非确定性，直接解决 RL 训练-推理概率失配问题，提高系统可靠性与可复现性；同时量化了确定性带来的延迟开销，为吞吐/延迟/成本权衡提供依据。
- 置信度：0.92

主要贡献：

- 识别不同 TP 大小下张量并行导致的非确定性，并分析其对基准评测和 RL 训练的影响。
- 提出 Tree-Based Invariant Kernels，通过固定且一致的 intra-GPU 矩阵乘与 inter-GPU All-Reduce 计算顺序，消除 TP 导致的非确定性。
- 将 TBIK 集成到 vLLM 和 FSDP，实现完全确定性推理并解决 RL 管线中的概率失配，支持真正的 on-policy RL。

局限：

- 确定性推理相对普通模式有显著开销（端到端 22%–63%），当前实现尚未达到生产级性能。
- Tree-Based MatMul 在小 M 时因固定 block-size 约束慢于 cuBLAS，BF16 下吞吐约为 cuBLAS 的 63%。
- 当前实现主要用于证明 TP 不变确定性推理的可行性，性能可通过 block size 调优、warp specialization 等进一步提升。
- 尚未支持量化数据类型，作者将把确定性保证扩展到量化设置列为未来工作。

证据：

- TBIK 的核心是使累积顺序与 TP 大小无关：通过固定的全二叉树归约拓扑统一本地 MatMul 与分布式集合通信的归约顺序，从而保证跨 TP 配置的确定性。 — “we impose a fixed full binary-tree reduction topology shared by local MatMul and distributed collective operations.”，p. 5
- 在实验中，BIO+TBIK 在所有实验设置下达到严格为零的最大概率散度，证明实现了逐位确定的 LLM 推理。 — “BIO+TBIK achieves a strictly zero Maximum Probability Divergence across all experimental settings, demonstrating bit-wise deterministic LLM inference.”，p. 7

### P32 · DeltaServe: Host-Agnostic Co-Serving of Inference and Fine-Tuning for LLMs

DeltaServe 提出一种与宿主无关（host-agnostic）的协同服务设计，在不增加硬件的前提下将空闲推理 GPU 容量转化为 LoRA 微调吞吐，并通过 SLO 感知调度、CUDA-graph 感知延迟模型和独立反向子进程来维持推理延迟目标。

- 分类：推理服务与请求调度, 训练系统与优化, 性能评测与成本分析
- 研究问题：以 vLLM 为代表的 AI Infra Systems 如何通过内存管理、请求调度、并行执行、低精度计算与软硬件协同，提高大模型训练和在线推理的吞吐、延迟、成本效率与可靠性？
- 方法：DeltaServe 采用组件式扩展而非替换宿主推理引擎：通过紧凑的 hook 接口仅要求宿主支持 multi-LoRA batching；将 LoRA 微调前向建模为 prefill-only 请求并混入推理 batch；利用解析延迟模型（区分 CUDA graph 与 eager 执行模式，离线校准并在线精修）计算每 batch 的 SLO 预算；反向传播在独立 GPU 子进程中执行，在 transformer 层边界让位给推理，并在 prefill 请求到达时被抢占；同一核心被集成到 vLLM、SGLang 和 S-LoRA 三个引擎。
- 实验设置：硬件包括单卡 NVIDIA RTX 5090 (32GB) 和 4×NVIDIA A100 (40GB) 服务器；模型使用 Llama 3-8B 作为共享基座，在 Alpaca 数据集上微调 rank=16 的 LoRA adapter（alpha=32, dropout=0.05）；推理负载为 burst-light、burst-dense 两个合成模式与 20 分钟 Nutanix 生产 trace；SLO 在 A100 上为 400ms TTFT/120ms TPOT，在 RTX 5090 上为 200ms TTFT/100ms TPOT；对照系统为 LLMStation 和 vLLM+torchtune split-pool 基线，并集成了 vLLM、SGLang、S-LoRA。
- 与综述主题的关系：该论文直接涉及 survey 中的请求调度、训练系统优化、软硬件协同与性能评测：DeltaServe 将推理 SLO 转化为每 batch 的动态预算，通过 SLO-aware 准入调度把空闲推理容量用于 LoRA 微调，并用 CUDA-graph-aware 延迟模型和独立 GPU 反向子进程实现协同执行；其无额外硬件下的吞吐提升和 SLO 合规数据也体现了成本效率与可靠性方面的收益。
- 置信度：0.92

主要贡献：

- 提出 host-agnostic 的协同服务设计：可复用的 DeltaServe 核心加紧凑集成 hooks，仅要求宿主引擎支持 multi-LoRA batching，并在 vLLM、SGLang、S-LoRA 三个引擎上验证。
- 设计 SLO-aware 微调准入调度：利用 LoRA 前向与推理 prefill 的结构一致性，将微调作为 prefill-only 请求并入推理 batch，按 TTFT/TPOT 预算准入和节流。
- 构建 CUDA-graph-aware 延迟模型：离线校准、在线精修的解析模型，显式区分 graph 与 eager 执行模式的延迟差异。
- 实现解耦反向执行器：独立 GPU 子进程负责反向传播和优化器更新，在层边界让位并可在新推理请求到达时抢占。
- 开源并在三种宿主引擎上完成端到端评测，展示 SLO 合规下的微调吞吐提升和可移植性。

局限：

- DeltaServe 要求宿主推理引擎至少支持 multi-LoRA batching；若宿主缺少该能力则无法直接集成。
- 混合 batch 因激活捕获 hooks 无法在回放的 CUDA graph 内运行而被迫使用 eager 执行，可能损失 CUDA graph 回放带来的低启动开销优势。
- 论文评估集中于 Llama 3-8B 和 Alpaca 数据集，未报告其他模型架构、更大模型或不同类型数据集上的行为。
- 反向子进程在 prefill 请求到达时会被抢占，突发推理负载下微调吞吐会明显下降，这是设计上的权衡。

证据：

- DeltaServe 的核心目标是把空闲推理容量转化为 LoRA 微调吞吐，同时保持推理 SLO 不变。 — “We present DeltaServe, a host-agnostic co-serving design that converts this idle inference capacity into LoRA fine-tuning throughput while preserving inference service-level objectives (SLOs).”，p. 1
- DeltaServe 的准入策略与 LLMStation 不同，它可以在任意推理阶段把微调建模为单步 prefill-only 请求，从而利用完整的推理延迟预算来调度微调。 — “DeltaServe instead admits fine-tuning in any phase, modeling each sample as a single-step, prefill-only request (Section 3), so it can admit against the full inference latency budget.”，p. 4

## 参考文献

- [P01] Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, Ion Stoica (2023). *Efficient Memory Management for Large Language Model Serving with PagedAttention*. arXiv:2309.06180. https://arxiv.org/abs/2309.06180v1
- [P02] Lianmin Zheng, Liangsheng Yin, Zhiqiang Xie, Chuyue Sun, Jeff Huang, Cody Hao Yu, Shiyi Cao, Christos Kozyrakis, Ion Stoica, Joseph E. Gonzalez, Clark Barrett, Ying Sheng (2023). *SGLang: Efficient Execution of Structured Language Model Programs*. arXiv:2312.07104. https://arxiv.org/abs/2312.07104v2
- [P03] Ramya Prabhu, Ajay Nayak, Jayashree Mohan, Ramachandran Ramjee, Ashish Panwar (2024). *vAttention: Dynamic Memory Management for Serving LLMs without PagedAttention*. arXiv:2405.04437. https://arxiv.org/abs/2405.04437v3
- [P04] Yuxin Wang, Yuhan Chen, Zeyu Li, Xueze Kang, Yuchu Fang, Yeju Zhou, Yang Zheng, Zhenheng Tang, Xin He, Rui Guo, Xin Wang, Qiang Wang, Amelie Chi Zhou, Xiaowen Chu (2024). *BurstGPT: A Real-world Workload Dataset to Optimize LLM Serving Systems*. arXiv:2401.17644. https://arxiv.org/abs/2401.17644v5
- [P05] Kan Zhu, Yufei Gao, Yilong Zhao, Liangyu Zhao, Gefei Zuo, Yile Gu, Dedong Xie, Tian Tang, Qinyu Xu, Zihao Ye, Keisuke Kamahori, Chien-Yu Lin, Ziren Wang, Stephanie Wang, Arvind Krishnamurthy, Baris Kasikci (2024). *NanoFlow: Towards Optimal Large Language Model Serving Throughput*. arXiv:2408.12757. https://arxiv.org/abs/2408.12757v2
- [P06] Biao Sun, Ziming Huang, Hanyu Zhao, Wencong Xiao, Xinyi Zhang, Yong Li, Wei Lin (2024). *Llumnix: Dynamic Scheduling for Large Language Model Serving*. arXiv:2406.03243. https://arxiv.org/abs/2406.03243v1
- [P07] Zirui Liu, Jiayi Yuan, Hongye Jin, Shaochen Zhong, Zhaozhuo Xu, Vladimir Braverman, Beidi Chen, Xia Hu (2024). *KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache*. doi:10.13140/RG.2.2.28167.37282. https://arxiv.org/abs/2402.02750v2
- [P08] Shimao Chen, Zirui Liu, Zhiying Wu, Ce Zheng, Peizhuang Cong, Zihan Jiang, Yuhan Wu, Lei Su, Tong Yang (2024). *INT-FlashAttention: Enabling Flash Attention for INT8 Quantization*. arXiv:2409.16997. https://arxiv.org/abs/2409.16997v2
- [P09] Jiayi Yao, Hanchen Li, Yuhan Liu, Siddhant Ray, Yihua Cheng, Qizheng Zhang, Kuntai Du, Shan Lu, Junchen Jiang (2024). *CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion*. arXiv:2405.16444. https://arxiv.org/abs/2405.16444v3
- [P10] Yuhan Liu, Hanchen Li, Yihua Cheng, Siddhant Ray, Yuyang Huang, Qizheng Zhang, Kuntai Du, Jiayi Yao, Shan Lu, Ganesh Ananthanarayanan, Michael Maire, Henry Hoffmann, Ari Holtzman, Junchen Jiang (2023). *CacheGen: KV Cache Compression and Streaming for Fast Large Language Model Serving*. arXiv:2310.07240. https://arxiv.org/abs/2310.07240v6
- [P11] Lingfan Yu, Jinkun Lin, Jinyang Li (2023). *Stateful Large Language Model Serving with Pensieve*. doi:10.1145/3689031.3696086. https://arxiv.org/abs/2312.05516v3
- [P12] Ao Shen, Zhiyao Li, Mingyu Gao (2024). *FastSwitch: Optimizing Context Switching Efficiency in Fairness-aware Large Language Model Serving*. arXiv:2411.18424. https://arxiv.org/abs/2411.18424v1
- [P13] Shiyi Cao, Yichuan Wang, Ziming Mao, Pin-Lun Hsu, Liangsheng Yin, Tian Xia, Dacheng Li, Shu Liu, Yineng Zhang, Yang Zhou, Ying Sheng, Joseph Gonzalez, Ion Stoica (2025). *Locality-aware Fair Scheduling in LLM Serving*. arXiv:2501.14312. https://arxiv.org/abs/2501.14312v1
- [P14] Chaoyi Ruan, Yinhe Chen, Dongqi Tian, Yandong Shi, Yongji Wu, Jialin Li, Cheng Li (2025). *DynaServe: Unified and Elastic Execution for Dynamic Disaggregated LLM Serving*. arXiv:2504.09285. https://arxiv.org/abs/2504.09285v2
- [P15] Xiaoxiang Shi, Colin Cai, Junjia Du, Zhihao Jia (2025). *Nexus:Proactive Intra-GPU Disaggregation of Prefill and Decode in LLM Serving*. arXiv:2507.06608. https://arxiv.org/abs/2507.06608v5
- [P16] Wan Borui, Zhao Juntao, Jiang Chenyu, Guo Chuanxiong, Wu Chuan (2025). *Efficient LLM Serving on Hybrid Real-time and Best-effort Requests*. arXiv:2504.09590. https://arxiv.org/abs/2504.09590v1
- [P17] Shi Qiu, Yifan Hu, Xintao Wang, Wenhao Zhu, Jianqin Yan, Hao Chen, Kaiqiang Xu, Kai Chen, Yiming Zhang (2026). *Tutti: Making SSD-Backed KV Cache Practical for Long-Context LLM Serving*. arXiv:2605.03375. https://arxiv.org/abs/2605.03375v1
- [P18] Dongha Yoon, Younghoon Min, Hoshik Kim, Sam H. Noh, Jongryool Kim (2025). *TraCT: Disaggregated LLM Serving with CXL Shared Memory KV Cache at Rack-Scale*. arXiv:2512.18194. https://arxiv.org/abs/2512.18194v1
- [P19] Zhiqiang Xie, Ziyi Xu, Mark Zhao, Yuwei An, Vikram Sharma Mailthody, Scott Mahlke, Michael Garland, Christos Kozyrakis (2025). *Strata: Hierarchical Context Caching for Long Context Language Model Serving*. arXiv:2508.18572. https://arxiv.org/abs/2508.18572v1
- [P20] Shaoting Feng, Hanchen Li, Kuntai Du, Zhuohan Gu, Yuhan Liu, Jiayi Yao, Siddhant Ray, Samuel Shen, Yihua Cheng, Ganesh Ananthanarayanan, Junchen Jiang (2025). *AdaptCache: KV Cache Native Storage Hierarchy for Low-Delay and High-Quality Language Model Serving*. arXiv:2509.00105. https://arxiv.org/abs/2509.00105v2
- [P21] Shaoting Feng, Yuhan Liu, Hanchen Li, Xiaokun Chen, Samuel Shen, Kuntai Du, Zhuohan Gu, Rui Zhang, Yuyang Huang, Yihua Cheng, Jiayi Yao, Qizheng Zhang, Ganesh Ananthanarayanan, Junchen Jiang (2025). *EVICPRESS: Joint KV-Cache Compression and Eviction for Efficient LLM Serving*. arXiv:2512.14946. https://arxiv.org/abs/2512.14946v1
- [P22] Jiayi Yao, Samuel Shen, Kuntai Du, Shaoting Feng, Dongjoo Seo, Rui Zhang, Yuyang Huang, Yuhan Liu, Shan Lu, Junchen Jiang (2026). *VeriCache: Turning Lossy KV Cache into Lossless LLM Inference*. arXiv:2605.17613. https://arxiv.org/abs/2605.17613v1
- [P23] Xinyue Ma, Heelim Hong, Taegeon Um, Jongseop Lee, Seoyeong Choy, Woo-Yeon Lee, Myeongjae Jeon (2026). *OrbitFlow: SLO-Aware Long-Context LLM Serving with Fine-Grained KV Cache Reconfiguration*. arXiv:2601.10729. https://arxiv.org/abs/2601.10729v2
- [P24] Yuanhang Gao, Xiangrui Yang, Yuanfeng Chen, Hongjia Chen, Qianru Lv, Wenfei Wu, Dongsheng Li (2026). *vToken: Token-Level Virtualization for Reclaimable KV Caches*. arXiv:2608.13263. https://arxiv.org/abs/2608.13263v1
- [P25] Akshat Sharma, Hangliang Ding, Jianping Li, Neel Dani, Minjia Zhang (2024). *MiniKV: Pushing the Limits of LLM Inference via 2-Bit Layer-Discriminative KV Cache*. arXiv:2411.18077. https://arxiv.org/abs/2411.18077v3
- [P26] Minsu Kim, Seongmin Hong, RyeoWook Ko, Soongyu Choi, Hunjong Lee, Junsoo Kim, Joo-Young Kim, Jongse Park (2025). *Oaken: Fast and Efficient LLM Serving with Online-Offline Hybrid KV Cache Quantization*. doi:10.1145/3695053.3731019. https://arxiv.org/abs/2503.18599v2
- [P27] Archit Patke, Dhemath Reddy, Saurabh Jha, Haoran Qiu, Christian Pinto, Chandra Narayanaswami, Zbigniew Kalbarczyk, Ravishankar Iyer (2024). *Queue management for slo-oriented large language model serving*. doi:10.1145/3698038.369852. https://arxiv.org/abs/2407.00047v2
- [P28] Yuxing Xiang, Xue Li, Kun Qian, Wenyuan Yu, Ennan Zhai, Xin Jin (2025). *ServeGen: Workload Characterization and Generation of Large Language Model Serving in Production*. arXiv:2505.09999. https://arxiv.org/abs/2505.09999v3
- [P29] Nada Zine, Tristan Coignion, Vincenzo Stoico, Clément Quinton, Ivano Malavolta, Romain Rouvoy, Patricia Lago (2026). *Attention to Detail: Evaluating Energy, Performance, and Accuracy Trade-offs Across vLLM Configurations*. arXiv:2607.09172. https://arxiv.org/abs/2607.09172v2
- [P30] Yunze Zhao, Yibo Zhao, Yuchen Zhang, Zaoxing Liu, Michelle L. Mazurek (2026). *Continuous Discovery of Vulnerabilities in LLM Serving Systems with Fuzzing*. arXiv:2605.11202. https://arxiv.org/abs/2605.11202v1
- [P31] Ziyang Zhang, Xinheng Ding, Jiayi Yuan, Rixin Liu, Huizi Mao, Jiarong Xing, Zirui Liu (2025). *Deterministic Inference across Tensor Parallel Sizes That Eliminates Training-Inference Mismatch*. arXiv:2511.17826. https://arxiv.org/abs/2511.17826v2
- [P32] Jiaxuan Chen, Jianshu She, Ye Yuan, Rajat Ghosh, Karan Gupta, Qirong Ho, Xue Liu, Oana Balmau (2026). *DeltaServe: Host-Agnostic Co-Serving of Inference and Fine-Tuning for LLMs*. arXiv:2607.28848. https://arxiv.org/abs/2607.28848v1
