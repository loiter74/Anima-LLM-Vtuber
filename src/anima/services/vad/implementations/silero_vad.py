"""
Silero VAD 实现
参考 Open-LLM-VTuber 的 VADEngine 和 StateMachine 实现
"""

from collections import deque
from typing import Union, Generator
import numpy as np
from loguru import logger

from ..interface import VADInterface, VADState, VADResult


class SileroVADConfig:
    """Silero VAD 配置"""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        prob_threshold: float = 0.4,
        db_threshold: int = 60,
        required_hits: int = 3,       # 开始说话需要的连续命中次数 (3 * 0.032s ≈ 0.1s)
        required_misses: int = 24,    # 停止说话需要的连续未命中次数 (24 * 0.032s ≈ 0.8s)
        smoothing_window: int = 5,    # 平滑窗口大小
    ):
        self.sample_rate = sample_rate
        self.prob_threshold = prob_threshold
        self.db_threshold = db_threshold
        self.required_hits = required_hits
        self.required_misses = required_misses
        self.smoothing_window = smoothing_window


class SileroVAD(VADInterface):
    """
    基于 Silero 的语音活动检测实现
    
    使用状态机检测语音的开始和结束：
    - IDLE -> ACTIVE: 检测到语音开始
    - ACTIVE -> INACTIVE: 检测到语音暂停
    - INACTIVE -> ACTIVE: 语音继续
    - INACTIVE -> IDLE: 语音完全结束，输出累积的音频
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        prob_threshold: float = 0.4,
        db_threshold: int = 60,
        required_hits: int = 3,
        required_misses: int = 24,
        smoothing_window: int = 5,
    ):
        self.config = SileroVADConfig(
            sample_rate=sample_rate,
            prob_threshold=prob_threshold,
            db_threshold=db_threshold,
            required_hits=required_hits,
            required_misses=required_misses,
            smoothing_window=smoothing_window,
        )
        
        # 窗口大小：16kHz 时为 512 采样点 (约 32ms)
        self.window_size_samples = 512 if sample_rate == 16000 else 256
        
        # 加载模型
        self.model = self._load_vad_model()
        
        # 状态机
        self.state_machine = SileroStateMachine(self.config)
        
        logger.info(f"Silero VAD 初始化完成: sample_rate={sample_rate}, "
                   f"prob_threshold={prob_threshold}, db_threshold={db_threshold}")
    
    def _load_vad_model(self):
        """加载 Silero VAD 模型"""
        try:
            from silero_vad import load_silero_vad
            logger.info("正在加载 Silero-VAD 模型...")
            model = load_silero_vad()
            logger.info("Silero-VAD 模型加载完成")
            return model
        except ImportError:
            logger.warning("silero-vad 未安装，请运行: pip install silero-vad")
            raise
        except Exception as e:
            logger.error(f"加载 Silero-VAD 模型失败: {e}")
            raise
    
    def detect_speech(self, audio_data: Union[list, np.ndarray]) -> VADResult:
        """
        检测音频数据中的语音活动
        
        处理流程：
        1. 将音频分块（每块 512 采样点）
        2. 对每块计算语音概率
        3. 通过状态机判断语音开始/结束
        
        Args:
            audio_data: 音频数据（float32 列表或 numpy 数组）
            
        Returns:
            VADResult: 检测结果
        """
        import torch
        
        # 转换为 numpy 数组
        audio_np = np.array(audio_data, dtype=np.float32)
        
        # 分块处理
        for i in range(0, len(audio_np), self.window_size_samples):
            chunk_np = audio_np[i: i + self.window_size_samples]
            
            if len(chunk_np) < self.window_size_samples:
                break
            
            # 转换为 torch 张量
            chunk_tensor = torch.Tensor(chunk_np)
            
            # 计算语音概率
            with torch.no_grad():
                speech_prob = self.model(chunk_tensor, self.config.sample_rate).item()
            
            # 通过状态机处理
            result = self.state_machine.process(speech_prob, chunk_np)
            
            if result is not None:
                return result
        
        # 没有特殊事件，返回当前状态
        return VADResult(
            audio_data=b"",
            is_speech_start=False,
            is_speech_end=False,
            state=self.state_machine.state
        )
    
    def reset(self) -> None:
        """重置状态机"""
        self.state_machine = SileroStateMachine(self.config)
        logger.debug("VAD 状态机已重置")
    
    def get_current_state(self) -> VADState:
        """获取当前状态"""
        return self.state_machine.state
    
    async def close(self) -> None:
        """清理资源"""
        self.reset()
        logger.info("Silero VAD 资源已释放")


class SileroStateMachine:
    """
    Silero VAD 状态机
    
    状态转换：
    IDLE -> ACTIVE: 连续命中 required_hits 次
    ACTIVE -> INACTIVE: 连续未命中 required_misses 次
    INACTIVE -> ACTIVE: 连续命中 required_hits 次
    INACTIVE -> IDLE: 连续未命中 required_misses 次（输出音频）
    """
    
    def __init__(self, config: SileroVADConfig):
        self.state = VADState.IDLE
        self.config = config
        
        # 计数器
        self.hit_count = 0
        self.miss_count = 0
        
        # 累积的音频数据
        self.probs = []
        self.dbs = []
        self.bytes = bytearray()
        
        # 平滑窗口
        self.prob_window = deque(maxlen=config.smoothing_window)
        self.db_window = deque(maxlen=config.smoothing_window)
        
        # 预缓冲（保存语音开始前的一些音频）
        self.pre_buffer = deque(maxlen=20)
    
    @staticmethod
    def calculate_db(audio_data: np.ndarray) -> float:
        """计算音频的分贝值"""
        rms = np.sqrt(np.mean(np.square(audio_data)))
        return 20 * np.log10(rms + 1e-7) if rms > 0 else -np.inf
    
    def get_smoothed_values(self, prob: float, db: float) -> tuple:
        """获取平滑后的概率和分贝值"""
        self.prob_window.append(prob)
        self.db_window.append(db)
        return np.mean(self.prob_window), np.mean(self.db_window)
    
    def update(self, chunk_bytes: bytes, prob: float, db: float) -> None:
        """更新累积数据"""
        self.probs.append(prob)
        self.dbs.append(db)
        self.bytes.extend(chunk_bytes)
    
    def reset_buffers(self) -> None:
        """重置缓冲区"""
        self.probs.clear()
        self.dbs.clear()
        self.bytes.clear()
    
    def process(self, prob: float, float_chunk_np: np.ndarray) -> Union[VADResult, None]:
        """
        处理音频块
        
        Args:
            prob: 语音概率
            float_chunk_np: float32 音频块
            
        Returns:
            VADResult 或 None（无特殊事件时）
        """
        # 转换为 int16 字节
        int_chunk_np = (float_chunk_np * 32767).astype(np.int16)
        chunk_bytes = int_chunk_np.tobytes()
        
        # 计算分贝值
        db = self.calculate_db(int_chunk_np)
        
        # 平滑处理
        smoothed_prob, smoothed_db = self.get_smoothed_values(prob, db)
        
        # 判断是否为语音
        is_speech = (
            smoothed_prob >= self.config.prob_threshold and
            smoothed_db >= self.config.db_threshold
        )
        
        # 状态机处理
        if self.state == VADState.IDLE:
            # 空闲状态：等待语音开始
            self.pre_buffer.append(chunk_bytes)
            
            if is_speech:
                self.hit_count += 1
                if self.hit_count >= self.config.required_hits:
                    # 检测到语音开始
                    self.state = VADState.ACTIVE
                    self.update(chunk_bytes, smoothed_prob, smoothed_db)
                    self.hit_count = 0
                    return VADResult(
                        audio_data=b"",
                        is_speech_start=True,
                        is_speech_end=False,
                        state=VADState.ACTIVE
                    )
            else:
                self.hit_count = 0
        
        elif self.state == VADState.ACTIVE:
            # 活跃状态：正在说话
            self.update(chunk_bytes, smoothed_prob, smoothed_db)
            
            if is_speech:
                self.miss_count = 0
            else:
                self.miss_count += 1
                if self.miss_count >= self.config.required_misses:
                    # 检测到语音暂停
                    self.state = VADState.INACTIVE
                    self.miss_count = 0
        
        elif self.state == VADState.INACTIVE:
            # 暂停状态：等待语音继续或结束
            self.update(chunk_bytes, smoothed_prob, smoothed_db)
            
            if is_speech:
                self.hit_count += 1
                if self.hit_count >= self.config.required_hits:
                    # 语音继续
                    self.state = VADState.ACTIVE
                    self.hit_count = 0
                    self.miss_count = 0
            else:
                self.hit_count = 0
                self.miss_count += 1
                if self.miss_count >= self.config.required_misses:
                    # 语音完全结束
                    self.state = VADState.IDLE
                    self.miss_count = 0
                    
                    # 只有累积了足够的音频才输出
                    if len(self.probs) > 30:
                        # 合并预缓冲和主缓冲区的音频
                        pre_bytes = b"".join(self.pre_buffer)
                        audio_data = pre_bytes + bytes(self.bytes)
                        
                        self.reset_buffers()
                        self.pre_buffer.clear()
                        
                        return VADResult(
                            audio_data=audio_data,
                            is_speech_start=False,
                            is_speech_end=True,
                            state=VADState.IDLE
                        )
                    
                    self.reset_buffers()
                    self.pre_buffer.clear()
        
        return None