"""测试设备自动降级"""
import sys
sys.path.insert(0, 'src')

from anima.services.llm.implementations.local_lora_llm import LocalLoraLLM

print("=" * 60)
print("测试设备自动降级")
print("=" * 60)
print()

# 测试1: 请求 cuda，但实际没有 GPU
print("测试1: 请求 CUDA（会自动降级）")
print("-" * 60)
llm = LocalLoraLLM(
    base_model_name="test",
    lora_path="test",
    device="cuda"  # 请求 cuda
)

print(f"请求设备: cuda")
print(f"实际设备: {llm.device}")
print(f"降级?: {llm.device != llm.requested_device}")
print()

# 测试2: 明确请求 cpu
print("测试2: 请求 CPU（不降级）")
print("-" * 60)
llm_cpu = LocalLoraLLM(
    base_model_name="test",
    lora_path="test",
    device="cpu"  # 请求 cpu
)

print(f"请求设备: cpu")
print(f"实际设备: {llm_cpu.device}")
print(f"降级?: {llm_cpu.device != llm_cpu.requested_device}")
print()

print("=" * 60)
print("✅ 设备降级测试完成！")
print("=" * 60)
