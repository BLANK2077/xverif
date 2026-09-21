# 验证环境理解对照：100 题

每题需给出中文答案、对应文件行号或具体查询证据，以及不确定性。Q091–Q095 的编译集合能力单列，不与共享推理成绩混算。所有数值推演均按题设，不代表本次仿真已发生。

## A 跨文件结构与类型

**Q001** 从三个 VIP monitor analysis port 一直追到 scoreboard 的消费函数，画出端口、export、FIFO、消费者对应关系；指出名为 analysis_export 的 FIFO 成员实际是什么 class。

**Q002** 给出 axi_multi_id_master_seq 到 uvm_void 的完整继承链，标出项目/SVT/UVM 边界；用 env 与 scoreboard 的关系解释为什么继承查询不能替代对象父子层次查询。

**Q003** master sequence 上调用 get_response(rsp,7) 时，声明 owner、形参方向/顺序/默认值及阻塞匹配条件是什么？这里的 7 能否直接理解成 AXI bus ID？

**Q004** 沿 master sequence 继承链追踪 pre_start/pre_body/get_sequence_initial_setup。解释配置为何不会因两个入口被重复初始化；不要假定每层同名方法都会自动调用。

**Q005** axi_virtual_sequencer.master_sequencer 的声明类型与 SVT master sequence 的 p_sequencer 有什么不同？沿赋值、start、p_sequencer 宏说明为什么静态基类 handle 不证明实际对象类型正确。

**Q006** 定位 svt_axi_transaction 的 burst_addr_mask、burst_length、burst_size、burst_size_str，逐一列 visibility/rand/类型；若在派生类里直接读四者，哪些访问边界必须区分？

**Q007** 从 scoreboard.master_fifo 的使用处追到参数化类定义与 get 的声明 owner。说明 T 的实际声明绑定、定义默认值、继承传播关系，并指出原始 Parameter 关系不能直接替代 actual binding。

**Q008** 列出 fixture 八个自定义 class 及直接基类，并按 UVM component、sequence、普通辅助对象分类；哪些通过 factory 创建，哪些直接 new？不要把辅助 snapshot 当成 uvm_object。

**Q009** 比较 svt_sequence、svt_axi_master_base_sequence、svt_axi_slave_base_sequence 的 REQ/RSP 类型传播，给出当前可证明的 master/slave 绑定；区分默认参数、宏条件分支和已编译绑定。

**Q010** axi_sb_read_snapshot 是否自动拥有 UVM clone/copy/factory 能力？比较 snapshot=new(xact)、另一个变量直接赋 snapshot handle、uvm_object.clone 三种语义，并指出 snapshot 保存哪些字段而不是整笔 transaction。

## B 配置传播与生命周期

**Q011** 当 +num_ids=3 +outstanding_depth=5 时，追踪 test→master sequence 和 env→master/slave cfg 两条配置路径，计算每方向/每 ID 深度与 VIP max_outstanding；解释为什么得到的两个数字不同。

**Q012** 把 +num_ids=17 +outstanding_depth=40 传入当前 test：sequence 中 valid_num_ids/valid_outstanding_depth 约束会自动拒绝这些直接赋值吗？给出赋值与 randomize 调用链，并区分 sequence 参数校验和 transaction randomize 失败。

**Q013** test 注释写参数可由 config_db override。若仅向 config_db 写 num_ids=8，不给 plusarg，能否据此断言 master 用 8？查实际读取代码并解释注释与实现的差异。

**Q014** axi_multi_id_test.build_phase 先 super.build_phase 再读取 plusargs，会不会因此必然导致 env 使用 test 的旧 num_ids？追踪 env 创建时机、配置函数的数据来源，说明能证明与不能证明的部分。

**Q015** 从 base test.run_phase 到 master_seq.start，列出 reset 等待、slave 启动、#100、master 启动、#10000 的顺序。哪些等待是明确 ns，哪些必须知道有效 timeunit；wait_for_reset 是否真的观察 reset 信号？

**Q016** 区分本环境 test 手工 objection、master pre/post_body 手工 starting_phase objection、UVM automatic_phase_objection 和 SVT manage_objection。仅设置 master_seq.starting_phase=phase 是否等于启用 UVM automatic_phase_objection？

**Q017** 给定 num_ids=3、trans_per_id=5、max_delay=300，主序列结束后 test 等待的写/读响应阈值分别多少，timeout 表达式算多少个当前时间单位？这个 timeout 能否捕获 master_seq.start 内部永久卡住？

**Q018** slave body 是 forever，test 最终 kill slave；结合 UVM kill 实现，slave 自定义 post_body 中的平均延迟报告会自然执行吗？区分正常完成、kill 和 disable fork 的作用。

**Q019** 如果 axi_system_env.master[0] 为 null，connect_phase 采取什么动作？这是否让 run_main_sequence 安全跳过 master？沿 virtual sequencer handle 与 start/p_sequencer 使用说明潜在失败点。

**Q020** 比较函数局部默认 num_ids=4/outstanding_depth=16、端口 ID 宽度4和 sequence num_ids约束1..16。说明默认 max_outstanding、支持的ID空间，以及 +num_ids=1 是否自动把总上限缩到16。

## C 主序列并发与反例

**Q021** num_ids=6、outstanding_depth=5，忽略 VIP 更严格限制时，代码本地最多允许多少笔在途请求？解释 issued/completed/in_flight 是全局共享还是按 ID/方向隔离，并说明上限不等于实测并发。

**Q022** num_ids=3、trans_per_id=5，假设所有发送成功：期望写、读 transaction 各多少；写 order_profile=(issued+id)%4 的四类次数分别多少？这些数能否直接当作 beat 数？

**Q023** 一笔请求抽到 addr=0xFF8、burst_len=16、每 beat 8 字节，按当前写/读函数的截断代码最终长度是多少，LEN 字段应是多少？指出 burst_length 和 AXI LEN 的差别。

**Q024** 设 mem_start_addr=0xFF8、mem_size=16，随机地址先取0x1000、burst_len=2。按代码先限制4KB再处理内存越界，最终 addr/len 是什么？是否需要重验4KB边界，默认配置为什么未暴露这个反例？

**Q025** single_beat_pct 取 -1 或 101 时，当前代码会怎样选择 single/burst？这个字段是否有明确0..100约束，test 直接赋值是否会触发约束求解？

**Q026** 比较写 profile0 与 profile1 的 data_before_addr、reference_event、首beat WVALID延迟和AW延迟；结合 slave READY配置，说明注释里的先后4周期依赖哪些条件。

**Q027** profile2 注释说 AW 和 W 同周期 handshake。列出它实际约束的 VALID/reference 字段，并解释若外部 READY 被延后，为何不能仅靠这段 randomize 断言握手同周期。

**Q028** +axi_profile=某个其它字符串 会让 axi_multi_id_master_seq 自动切换写延迟算法吗？限定在这个 class 的实现内追踪读取点与所有使用点，并与 ai_complex_delay_mode 所在 class 区分。

**Q029** 写 profile3 中 data_before_addr 的两种取值分别允许哪些参考事件与延迟范围？为什么不能把宏观随机 profile 的所有样本都称为 AW-first 或 W-first 已观测结果？

**Q030** 追踪本例先 xact.randomize 再 uvm_send 的 UVM 宏调用链。uvm_send 会不会再次 randomize？宏返回、item_done、wait_for_transaction_end 三者能否视为同一完成点？

**Q031** 按 join_none 子进程等父线程挂起才开始执行的语义，比较 body 中 current_id 与 send_* 中 wait_xact 的声明位置。仅有 automatic 是否保证每个子线程捕获正确 xact？给出需要警惕的重赋值路径，区分风险推演与已复现故障。

**Q032** 如果一个 wait_for_transaction_end 永不返回，send_write_transactions 的发起/等待/退出路径如何变化？结合 test 的 timeout 所在位置，说明哪里有等待上限，哪里没有。

**Q033** 本例的 read 是逐笔重放对应 write 地址，还是独立生成？多 ID 读写何时并行，是否存在先完成全部写再开始读的屏障；这对 scoreboard 初始数据可比性有什么影响？

**Q034** 列出写与读 randomize 中显式调整的动态数组、burst类型/大小和字节使能约束；结合 scoreboard 的地址步长和写数据存储说明它目前依赖什么流量子集。

**Q035** xact.randomize 返回0时本例采取什么动作？是否有缩短 burst、换 seed 或降低并发的重试路径；先前地址修正是否等于失败后的 fallback？

## D 从序列与响应策略

**Q036** 按 slave_seq 默认 mem_start_addr=0、mem_size=0x10000 和 pre_body 循环，初始化多少个64位word、最后一次写地址是什么？与 env 的slave地址范围比较，能否说整个可寻址范围都已初始化？

**Q037** slave pre_body 已随机初始化存储器，scoreboard 为什么仍可能对最早的读不做数据比较？追踪初始化数据有没有进入 expected_mem，以及 snapshot.compare_valid 的生成条件。

**Q038** 非 complex 模式下，连续四个响应选用哪些 delay profile？如果 min_resp_delay=100、max_resp_delay=300，能否宣称每个 BVALID/RVALID delay 都位于100..300？

**Q039** complex 模式，在本次响应计数更新之前：wr=0/rd=0 与 wr=8/rd=6 两种状态分别得到 bvalid_delay/rvalid_delay 多少？说明多条件同时命中时谁优先。

**Q040** complex 模式的 B/R delay 是按全局事务序号交替，还是分别按写/读响应计数决定？若在 wr_count 固定时连续处理读，bvalid_delay 相关计算是否仍可能重复；日志 profile 是否完整编码最终延迟？

**Q041** slave body 用 response_request_port.peek 而不是 get，随后 randomize、内存操作、uvm_send。只看到这段代码能否断言请求一定被重复处理？指出还要追踪哪个消费/driver握手关系，不要凭方法名下结论。

**Q042** slave body 如何取得配置、检查类型、把配置交给 req_resp？给出 randomize、写/读内存辅助任务、send 的顺序；配置 cast 或 randomize 失败会发生什么。

**Q043** 将 master 与 slave 两端约束连起来：哪些地方固定 OKAY、WREADY/AR-AW READY 延迟为0、RREADY延迟为0？由此能否断言所有通道没有backpressure或所有真实响应必定OKAY？

**Q044** slave 的 total_rdelay/avg_rdelay 是每个beat延迟总和、按beat加权平均，还是每笔read的首beat值？结合 forever+kill，解释报告是否必然可见。

**Q045** slave 内存读写与计数分支使用 get_transmitted_channel，scoreboard 使用 xact_type。仅凭字段名能否断言所有 VIP 状态下二者恒等？给出本例两处消费证据，并说明验证该不变量需要什么。

## E Scoreboard 数据流与漏检反例

**Q046** 说明 expected_mem、in_flight_writes、read_snapshots、snapshot.compare_valid/expected_data 的容器类型和元素类型。为什么事务 handle 队列、地址关联数组与逐beat动态数组不能互相当作相同的索引模型？

**Q047** write addr=0x1080、burst_length=4、burst_size=3 时，in_flight range 的 first/last 是什么？has_in_flight_write(0x109B) 返回什么；它和最后一个beat实际占用字节的差别为什么在当前对齐流量下较隐蔽？

**Q048** remove_in_flight_write 用哪些字段匹配？若队列里有两条完全相同的记录，一次完成删除几条；若同地址/ID但长度不同会怎样，缺少匹配会不会报错？

**Q049** find_read_snapshot 用什么键，重复的同地址/ID/len/size snapshot 如何选取？这个键能否证明匹配到唯一的 UVM transaction，若完成顺序不同会有什么风险？

**Q050** 一个三beat read 开始时，beat0 在 expected_mem 且无在途写，beat1 已知但有在途写，beat2 不在 expected_mem。完成时beat0数据错误、beat1/2任意：比较有效位与 OK/error 计数各怎样变化？假设正常找到该 snapshot。

**Q051** read started 时某beat因 in-flight write 失效，随后该write在read完成前结束并更新 expected_mem；此beat会自动恢复比较吗？给出 snapshot 建立、写完成、读完成三段证据。

**Q052** read started 时快照保存某地址A的值0x11且valid=1；后来另一个write把expected_mem[A]变成0x22；read完成返回0x11。会与哪一个值比较、计数如何，说明它为何保存快照。

**Q053** read完成时找不到snapshot，但expected_mem里有该地址；返回数据与expected_mem明显不同。当前代码会增加哪个计数，是否调用uvm_error？据此评价 num_compare_ok 的含义。

**Q054** 存在有效snapshot，但返回 data 数组比 snapshot.compare_valid 更长；多出的beat如何处理？反过来返回beat更少，缺失beat是否产生错误？限定现有scoreboard逻辑。

**Q055** 如果将刺激扩成 partial WSTRB、FIXED/WRAP burst或窄传输，scoreboard 当前哪些假设会失效？至少给出地址推进和数据更新两个具体实现点，并与当前master约束对应。

**Q056** snapshot.expected_data 和 expected_mem 是二态还是四态？假设上游能提供含X/Z的四态数据，赋给这些存储后能否保留未知态并据此做X检测；不要把这个假设说成当前VIP必然产生X。

**Q057** 构造一个 num_compare_error=0 但没有完成有效读数据比较的场景。report_phase 是否仍打印 TEST PASSED？它有没有检查 transaction 总量、队列清空和有效比较覆盖率？

**Q058** AXI_EXPECTED_TXN_JSON 的 request_index、completion_order、id_index、resp、latency_ps 分别来自哪里？为何它不是独立记录请求发起顺序、真实响应状态和真实延迟的完整oracle？

**Q059** JSON 字段 completion_time_ps 赋值自什么表达式，代码是否显式换算成ps？burst_length=0与1时len字段分别是什么，beat_count又是什么；指出单位与编码各自的证据边界。

**Q060** 三个FIFO各自forever消费是否意味着 master/slave transaction 已逐笔匹配并验证数量一致？指出代码实际关联机制、master消费职责，以及可以漏掉的检查。

## F UVM 库语义与调用链

**Q061** 对本例 analysis FIFO，创建后size()/used()/is_full()分别意味着什么？若写入三笔尚未取走，三个结果是多少；为什么 size()==0 不表示空？

**Q062** 追踪 monitor analysis write 经 scoreboard export、FIFO.analysis_export 到 mailbox 的调用链。链路会自动 clone transaction 吗；生产者发送后修改同一对象可能影响什么？

**Q063** 同一 uvm_analysis_port 连接两个 subscriber，其中先被调用的 subscriber 修改传入对象字段。第二个必然看到独立副本吗？依据write遍历与参数语义说明风险，避免假定连接顺序就是注册顺序。

**Q064** 比较 uvm_tlm_fifo 的 get、peek、try_get、try_peek：谁移除元素，谁阻塞，谁触发 get_ap；解释如果监测get_ap来统计消费者活动会漏掉什么。

**Q065** uvm_tlm_fifo 中假设 m.num()==1 且 m_pending_blocked_gets==1，can_get/can_peek/is_empty 分别返回什么？这说明 can_get 与是否有数据为什么不等价？

**Q066** uvm_tlm_fifo.flush 是否只静默清空mailbox？追踪内部try_get与get_ap，并指出它何时可能报告 flush failed；不要把注释中的空保证代替实际条件分支。

**Q067** response queue依次放入 transaction_id 为9、4、9的三个response。get_response(...,9)返回哪一个，随后get_response默认参数返回哪一个；如果要的ID不存在，底层等待的是什么条件？

**Q068** 设置 response_queue_depth=2，依次放A/B/C且不取出。error_report_disabled=0与1时，队列内容和错误报告有什么差异？关闭报告是否意味着C被保留？

**Q069** 比较 response_queue_depth=-1 与0；再核对 set_response_queue_error_report_disabled 附近注释和 put_base_response 的实际条件。说明哪个值关闭报告，发现文档与实现矛盾时以什么为证。

**Q070** use_response_handler(1) 后，sequencer 将response送往哪里？若用户没有 override 默认空response_handler，再去get_response，能否指望同一response已经入队？给出分派与默认实现证据。

**Q071** 将 master_seq.start 的 call_pre_post 参数设为0（只做思想实验）：UVM 跳过哪些回调、仍执行哪些回调？结合 SVT master 的 pre_start，是否必然丢失cfg初始化；本项目pre_body内的行为又有哪些会丢失？

**Q072** 若本项目 master_seq 已在pre_body手工raise starting_phase objection，随后被外部kill，UVM kill会自动调用其post_body配对drop吗？区分 UVM automatic objection 的清理与用户手工raise的风险。

**Q073** start_item 接收null、传入sequence对象、或找不到sequencer时分别怎样处理？明确其选取显式sequencer、item.get_sequencer、当前sequence.get_sequencer的优先顺序。

**Q074** 比较 finish_item 与 get_response 的等待对象和调用路径。如果driver调用item_done但尚未发送response，finish_item是否一定继续阻塞到response到来？把结果联系到本例独立的transaction_end等待。

**Q075** set_id_info(request)复制哪两个ID？sequencer如何按它们路由response，get_response又用哪个筛选；为什么这仍不代表AXI ID字段会被复制或匹配？

**Q076** uvm_object.clone 的实现是否意味着对任意派生对象所有字段做深拷贝？给出create→copy→field_automation/do_copy链，说明缺少字段注册/override会怎样，并区分handle赋值。

**Q077** uvm_object.copy(null)会清空目标对象吗？copy内部如何避免重复递归拷贝，何时清理copy map；不要把cycle check说成所有字段都已复制。

**Q078** 一个uvm_object派生类只有utils注册，没有field宏，也没有do_compare override。compare返回true能否证明所有用户字段相同？结合默认do_compare和comparer结果解释。

**Q079** 同一个time-slice里先trigger事件再调用wait_trigger或wait_ptrigger，行为为何不同？persistent trigger是否表示跨任意仿真时间一直不阻塞；它与is_on的持久状态有什么区别？

**Q080** uvm_barrier 阈值3已有两个waiter时调用set_threshold(2)，依据实现会怎样唤醒/重置？若auto_reset=0，新来一个waiter是否可因为旧的两人曾达到2就必然直通？

## G 配置库、factory 与 SVT 交叉验证

**Q081** env用config_db::set(this,"axi_system_env","cfg",axi_cfg)。若env完整名是uvm_test_top.env，最终scope是什么；cntxt=null或inst_name为空时算法如何变化？给出实际实现而非只背用法。

**Q082** 同一field在build阶段分别由test与更深的env设置，哪个优先？随后run阶段由低层组件再set时会怎样？解释precedence和同优先级顺序，不能一概说最后一次set永远赢。

**Q083** 如果相同scope与field_name分别用config_db#(int)写、config_db#(string)读，会仅因名字相同就命中吗？依据get查找的type handle与返回值，说明缺失时输出value是否被赋新值。

**Q084** 沿 component type_id::create 追到factory：parent/context/name如何组成匹配路径；同一请求同时有匹配instance override和type override时谁优先？多个instance规则命中时如何选择？

**Q085** 已注册A→B的type override，再注册A→C，replace=0与1分别有什么结果？若override链成环，find_override_by_type是否无界递归；指出报错与返回行为。

**Q086** 比较VIP自带svt_axi_slave_memory_sequence与本fixture axi_slave_mem_delayed_seq：前者默认OKAY/EXOKAY/SLVERR/DECERR权重、config_db读取类型是什么；后者是否继承并沿用这套随机响应策略？

**Q087** fixture master 没有显式调用sink_responses，就能断言第9个response发生默认深度8溢出吗？检查SVT master base constructor、sink_responses与UVM队列实现，说明容量、消费与内存占用是不同问题。

**Q088** SVT slave base 的 instantiate_axi_slave_mem、put_write_transaction_data_to_mem、get_read_data_from_mem_to_transaction 有哪些公开签名/注释？对第一个方法的名字作“必定新建内存”推断为何不可靠；受保护实现可以证明到什么程度？

**Q089** 在svt_axi_transaction直接方法中筛选名字含response的方法，给出完整目标集合与可读声明位置；若数据库指向受保护实现行，怎样区分声明、实现位置与可读取方法体？

**Q090** 源码树包含不同工具/宏变体的同名SVT类，且SVT_AXI_MASTER_TRANSACTION_TYPE存在不同定义。如何确认本次使用的class定义/类型，而不是选第一个rg命中？请给当前可证明的文件/分支证据及不足。

## H 编译集合能力（单列评分）

**Q091** 给出本次已编译数据库中package-like scope与class精确数量，区分有名称的package和临时命名的compilation unit。若你的工具不能证明精确编译集合，明确说明，不能用文本grep计数代替。

**Q092** 按scope给出本次所有class的分布，并核对和总数一致。哪些scope没有class，fixture自定义类落在哪里；不要把磁盘文件目录当package归属。

**Q093** 给出索引中的property/method/constraint/parameter原始记录数与合计。它们是否等于唯一成员声明数？说明同path重复记录、分页截断与完整计数的关系。

**Q094** 列出本次uvm_pkg里class名称匹配glob *sequence* 的完整集合与数量。只算class定义，不能混入typedef、方法、变量或未编译版本；不能证明完整时明确限定结果。

**Q095** 查询uvm_pkg::uvm_pool::pool时，能否保证selector唯一对应一条索引记录？报告当前结果与记录种类；如果歧义，合理的API行为是什么，不能静默选择第一条。

## I 宏、来源一致性与运行时边界

**Q096** axi_scoreboard.get_type 定位到utils宏调用行时，能否把这一行当完整手写方法体？追踪宏到registry类型，并说明需要怎样的来源标记区分调用点、生成方法与宏展开。

**Q097** 工具返回当前磁盘源码sha256和编译数据库行号时，能否证明文本就是编译时版本？若文件在编译后改过，怎样区分内容漂移、行号仍有效但语义失配、以及读期间文件变化？

**Q098** 对于SVT受保护方法，静态库能返回签名/类成员/源位置，就意味着AI可以看完整实现吗？分别说明可以回答的结构问题、不能回答的算法问题，以及源码读取遇保护区应怎样处理。

**Q099** 在当前编译索引查不到一个class或某个继承成员，能否断言整个磁盘工程都不存在它？结合条件编译、未实例化/未收录集合、继承筛选与分页，提出可核验的否定结论边界。

**Q100** 仅用此次静态源码/索引，能否断言仿真100ns的factory替换最终类型、对象成员值、virtual调用最终目标？区分默认test时间路径能推导的条件结论与真正的运行时观测，并列出所缺证据。

