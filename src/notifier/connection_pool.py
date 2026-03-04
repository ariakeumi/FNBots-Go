"""
HTTP连接池管理
"""

import logging
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

@dataclass
class PoolStats:
    """连接池统计信息"""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    connection_errors: int = 0
    timeout_errors: int = 0
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'failed_requests': self.failed_requests,
            'connection_errors': self.connection_errors,
            'timeout_errors': self.timeout_errors,
            'success_rate': f"{self.success_rate:.1f}%"
        }

class ConnectionPool:
    """HTTP连接池"""
    
    def __init__(self, 
                 pool_size: int = 10,
                 max_retries: int = 3,
                 timeout: int = 10,
                 backoff_factor: float = 0.3):
        """
        初始化连接池
        
        Args:
            pool_size: 连接池大小
            max_retries: 最大重试次数
            timeout: 超时时间（秒）
            backoff_factor: 退避因子
        """
        self.pool_size = pool_size
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_factor = backoff_factor
        
        # 创建Session
        self.session = self._create_session()
        
        # 统计信息
        self.stats = PoolStats()
        self.stats_lock = threading.Lock()
        self._session_headers_lock = threading.Lock()
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        self.logger.info(f"HTTP连接池初始化，大小: {pool_size}")
    
    def _create_session(self) -> requests.Session:
        """创建并配置Session"""
        session = requests.Session()
        
        # 配置重试策略
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"]
        )
        
        # 创建适配器
        adapter = HTTPAdapter(
            pool_connections=self.pool_size,
            pool_maxsize=self.pool_size,
            max_retries=retry_strategy
        )
        
        # 挂载适配器
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 设置默认请求头
        session.headers.update({
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'FN-Log-Monitor/1.0',
            'Accept': 'application/json'
        })
        
        return session
    
    def post(self, url: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        发送POST请求
        
        Args:
            url: 请求URL
            data: 请求数据
            
        Returns:
            响应数据或None
        """
        # 更新统计
        with self.stats_lock:
            self.stats.total_requests += 1
        
        try:
            response = self.session.post(
                url,
                json=data,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            
            result = None
            try:
                result = response.json()
            except Exception:
                result = None
            
            # 企业微信/钉钉通常含 errcode；若存在且不为 0，视为失败
            if isinstance(result, dict) and 'errcode' in result and result.get('errcode') != 0:
                self.logger.error(f"API返回错误: {result}")
                with self.stats_lock:
                    self.stats.failed_requests += 1
                return None
            
            # 其他平台以 HTTP 2xx 作为成功
            with self.stats_lock:
                self.stats.successful_requests += 1
            return result if result is not None else {}

        except requests.exceptions.Timeout:
            self.logger.error(f"POST请求超时 (timeout={self.timeout}s): {url}")
            with self.stats_lock:
                self.stats.timeout_errors += 1
                self.stats.failed_requests += 1
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"POST连接错误: {url} - {str(e)}")
            with self.stats_lock:
                self.stats.connection_errors += 1
                self.stats.failed_requests += 1
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"POST HTTP错误: {url} - 状态码: {e.response.status_code if e.response else 'N/A'} - {str(e)}")
            with self.stats_lock:
                self.stats.failed_requests += 1
        except Exception as e:
            self.logger.error(f"POST请求异常: {url} - {type(e).__name__}: {str(e)}", exc_info=True)
            with self.stats_lock:
                self.stats.failed_requests += 1
        
        return None
    
    def get(self, url: str) -> bool:
        """
        发送GET请求（用于Bark等GET类型的推送）
        
        Args:
            url: 请求URL
            
        Returns:
            请求是否成功
        """
        # 更新统计
        with self.stats_lock:
            self.stats.total_requests += 1
        
        try:
            # 临时移除 Content-Type 以免 GET 请求误带；用锁保护避免多线程并发修改 session.headers
            with self._session_headers_lock:
                original_content_type = self.session.headers.get('Content-Type')
                if original_content_type:
                    del self.session.headers['Content-Type']
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout
                )
            finally:
                with self._session_headers_lock:
                    if original_content_type:
                        self.session.headers['Content-Type'] = original_content_type
            
            if response.status_code < 400:
                with self.stats_lock:
                    self.stats.successful_requests += 1
                return True
            else:
                self.logger.error(f"GET请求失败: {response.status_code}")
                with self.stats_lock:
                    self.stats.failed_requests += 1
                return False

        except requests.exceptions.Timeout:
            self.logger.error(f"GET请求超时 (timeout={self.timeout}s): {url}")
            with self.stats_lock:
                self.stats.timeout_errors += 1
                self.stats.failed_requests += 1
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"GET连接错误: {url} - {str(e)}")
            with self.stats_lock:
                self.stats.connection_errors += 1
                self.stats.failed_requests += 1
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"GET HTTP错误: {url} - 状态码: {e.response.status_code if e.response else 'N/A'} - {str(e)}")
            with self.stats_lock:
                self.stats.failed_requests += 1
        except Exception as e:
            self.logger.error(f"GET请求异常: {url} - {type(e).__name__}: {str(e)}", exc_info=True)
            with self.stats_lock:
                self.stats.failed_requests += 1
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self.stats_lock:
            return self.stats.to_dict()
    
    def close(self):
        """关闭连接池"""
        self.session.close()
        self.logger.info("HTTP连接池已关闭")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.close()
