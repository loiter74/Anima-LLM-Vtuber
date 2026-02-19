"""
TTS 任务管理器
用于管理 TTS 异步任务的创建、追踪和等待
参考 Open-LLM-VTuber 的 TTSTaskManager 实现
"""

import asyncio
from typing import List, Optional, Dict, Any, Callable
from loguru import logger


class TTSTaskManager:
    """
    TTS 任务管理器
    
    管理当前对话中所有 TTS 任务的 lifecycle
    """
    
    def __init__(self):
        # 当前活跃的 TTS 任务列表
        self.task_list: List[asyncio.Task] = []
        
        # 任务结果存储
        self._results: Dict[str, Any] = {}
        
        # 是否已被打断
        self._interrupted: bool = False
    
    def add_task(self, task: asyncio.Task, task_id: Optional[str] = None) -> None:
        """
        添加一个 TTS 任务到管理器
        
        Args:
            task: asyncio Task 对象
            task_id: 可选的任务 ID，用于后续检索结果
        """
        if self._interrupted:
            logger.debug("TTS 已被打断，跳过新任务")
            return
        
        self.task_list.append(task)
        
        if task_id:
            task.add_done_callback(
                lambda t: self._store_result(task_id, t)
            )
        
        logger.debug(f"添加 TTS 任务，当前任务数: {len(self.task_list)}")
    
    def _store_result(self, task_id: str, task: asyncio.Task) -> None:
        """存储任务结果"""
        try:
            if not task.cancelled():
                self._results[task_id] = task.result()
        except Exception as e:
            logger.error(f"TTS 任务 {task_id} 执行出错: {e}")
    
    def get_result(self, task_id: str) -> Optional[Any]:
        """获取指定任务的执行结果"""
        return self._results.get(task_id)
    
    async def wait_all(self) -> None:
        """
        等待所有 TTS 任务完成
        
        如果有任务被取消或出错，会记录日志但不会抛出异常
        """
        if not self.task_list:
            return
        
        try:
            await asyncio.gather(*self.task_list, return_exceptions=True)
            logger.debug(f"所有 TTS 任务已完成，共 {len(self.task_list)} 个")
        except asyncio.CancelledError:
            logger.info("TTS 任务等待被取消")
        except Exception as e:
            logger.error(f"等待 TTS 任务时出错: {e}")
    
    def interrupt(self) -> None:
        """
        打断所有 TTS 任务
        
        取消所有正在进行的任务
        """
        self._interrupted = True
        
        for task in self.task_list:
            if not task.done():
                task.cancel()
        
        logger.info(f"已打断 {len(self.task_list)} 个 TTS 任务")
    
    def is_interrupted(self) -> bool:
        """检查是否已被打断"""
        return self._interrupted
    
    def clear(self) -> None:
        """
        清空所有任务（不取消正在执行的任务）
        """
        self.task_list.clear()
        self._results.clear()
        self._interrupted = False
    
    @property
    def pending_count(self) -> int:
        """获取待完成任务数量"""
        return sum(1 for task in self.task_list if not task.done())
    
    @property
    def completed_count(self) -> int:
        """获取已完成任务数量"""
        return sum(1 for task in self.task_list if task.done())