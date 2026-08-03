"""Evidence IR：预留给后续波形/反例解释使用。

当前仅定义证据合同，不包含波形取证实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvidenceIR:
    """波形证据 IR 合同。"""

    schema_version: str = "xsva.evidence_ir.v1"
    property_name: str = ""
    # 后续扩展: signal_samples, counterexample, waveform_references 等
