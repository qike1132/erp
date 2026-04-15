"""
ERP 服务器管理器 GUI
功能: 
  - 图形化管理 FastAPI (5002) 和 Flask (5003) 服务器
  - 后台运行,无独立控制台窗口
  - 实时监控服务器状态
  - 日志查看和错误处理
"""
import os
import sys
import subprocess
import threading
import time
import signal
import logging
from datetime import datetime
from pathlib import Path

# Windows平台特殊处理
if sys.platform == 'win32':
    import io
    # 确保UTF-8编码
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# psutil为可选依赖,用于进程管理
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class ServerManagerApp:
    """ERP服务器管理器主应用类"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("ERP 服务器管理器 v2.0")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        # 设置窗口图标(如果有的话)
        # self.root.iconbitmap('icon.ico')
        
        # 服务器进程
        self.fastapi_process = None
        self.flask_process = None
        
        # 服务器状态
        self.fastapi_running = False
        self.flask_running = False
        
        # 日志配置
        self.setup_logging()
        
        # 创建GUI
        self.create_widgets()
        
        # 启动状态检查定时器
        self.check_status_interval = 2000  # 2秒
        self.check_server_status()
        
        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.logger.info("服务器管理器已启动")
    
    def setup_logging(self):
        """配置日志系统"""
        log_dir = Path(__file__).parent / 'logs'
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / f'server_manager_{datetime.now().strftime("%Y%m%d")}.log'
        
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('server_manager')
    
    def create_widgets(self):
        """创建GUI组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # ===== 标题区域 =====
        title_frame = ttk.LabelFrame(main_frame, text="ERP 服务器管理系统", padding="10")
        title_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        title_frame.columnconfigure(0, weight=1)
        
        title_label = ttk.Label(
            title_frame, 
            text="滨发协同系统 - 生产服务器管理器",
            font=('Microsoft YaHei UI', 14, 'bold')
        )
        title_label.grid(row=0, column=0, pady=5)
        
        subtitle_label = ttk.Label(
            title_frame,
            text="FastAPI (5002) + Flask (5003) | 后台运行模式",
            font=('Microsoft YaHei UI', 9)
        )
        subtitle_label.grid(row=1, column=0)
        
        # ===== 服务器状态面板 =====
        status_frame = ttk.LabelFrame(main_frame, text="服务器状态", padding="10")
        status_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        status_frame.columnconfigure(0, weight=1)
        
        # FastAPI状态
        fastapi_status_frame = ttk.Frame(status_frame)
        fastapi_status_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        fastapi_status_frame.columnconfigure(1, weight=1)
        
        ttk.Label(fastapi_status_frame, text="FastAPI 服务:", width=15).grid(row=0, column=0, sticky=tk.W)
        self.fastapi_status_label = ttk.Label(fastapi_status_frame, text="● 已停止", foreground='red')
        self.fastapi_status_label.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        self.fastapi_pid_label = ttk.Label(fastapi_status_frame, text="PID: -")
        self.fastapi_pid_label.grid(row=0, column=2, sticky=tk.W, padx=5)
        
        # Flask状态
        flask_status_frame = ttk.Frame(status_frame)
        flask_status_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        flask_status_frame.columnconfigure(1, weight=1)
        
        ttk.Label(flask_status_frame, text="Flask 服务:", width=15).grid(row=0, column=0, sticky=tk.W)
        self.flask_status_label = ttk.Label(flask_status_frame, text="● 已停止", foreground='red')
        self.flask_status_label.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        self.flask_pid_label = ttk.Label(flask_status_frame, text="PID: -")
        self.flask_pid_label.grid(row=0, column=2, sticky=tk.W, padx=5)
        
        # ===== 控制按钮 =====
        control_frame = ttk.LabelFrame(main_frame, text="服务器控制", padding="10")
        control_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        control_frame.columnconfigure(0, weight=1)
        
        # 按钮框架
        button_frame = ttk.Frame(control_frame)
        button_frame.grid(row=0, column=0, pady=10)
        
        # 启动FastAPI按钮
        self.start_fastapi_btn = ttk.Button(
            button_frame,
            text="启动 FastAPI (5002)",
            command=self.start_fastapi,
            width=25
        )
        self.start_fastapi_btn.grid(row=0, column=0, padx=5, pady=5)
        
        # 停止FastAPI按钮
        self.stop_fastapi_btn = ttk.Button(
            button_frame,
            text="停止 FastAPI",
            command=self.stop_fastapi,
            state=tk.DISABLED,
            width=25
        )
        self.stop_fastapi_btn.grid(row=0, column=1, padx=5, pady=5)
        
        # 启动Flask按钮
        self.start_flask_btn = ttk.Button(
            button_frame,
            text="启动 Flask (5003)",
            command=self.start_flask,
            width=25
        )
        self.start_flask_btn.grid(row=1, column=0, padx=5, pady=5)
        
        # 停止Flask按钮
        self.stop_flask_btn = ttk.Button(
            button_frame,
            text="停止 Flask",
            command=self.stop_flask,
            state=tk.DISABLED,
            width=25
        )
        self.stop_flask_btn.grid(row=1, column=1, padx=5, pady=5)
        
        # 全部启动/停止按钮
        self.start_all_btn = ttk.Button(
            button_frame,
            text="全部启动",
            command=self.start_all,
            width=25
        )
        self.start_all_btn.grid(row=2, column=0, padx=5, pady=5)
        
        self.stop_all_btn = ttk.Button(
            button_frame,
            text="全部停止",
            command=self.stop_all,
            state=tk.DISABLED,
            width=25
        )
        self.stop_all_btn.grid(row=2, column=1, padx=5, pady=5)
        
        # 重启按钮
        self.restart_btn = ttk.Button(
            button_frame,
            text="重启服务器",
            command=self.restart_all,
            state=tk.DISABLED,
            width=25
        )
        self.restart_btn.grid(row=3, column=0, columnspan=2, padx=5, pady=5)
        
        # ===== 日志查看器 =====
        log_frame = ttk.LabelFrame(main_frame, text="实时日志", padding="10")
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        # 创建带滚动条的文本框
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=15,
            wrap=tk.WORD,
            font=('Consolas', 9),
            state=tk.DISABLED
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 日志控制按钮
        log_button_frame = ttk.Frame(log_frame)
        log_button_frame.grid(row=1, column=0, pady=5)
        
        ttk.Button(
            log_button_frame,
            text="清空日志",
            command=self.clear_log
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            log_button_frame,
            text="导出日志",
            command=self.export_log
        ).pack(side=tk.LEFT, padx=5)
        
        # ===== 底部状态栏 =====
        status_bar_frame = ttk.Frame(main_frame)
        status_bar_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        self.status_bar_label = ttk.Label(
            status_bar_frame,
            text="就绪",
            font=('Microsoft YaHei UI', 9)
        )
        self.status_bar_label.pack(side=tk.LEFT)
        
        # 访问链接
        ttk.Label(
            status_bar_frame,
            text="FastAPI: http://localhost:5002  |  Flask: http://localhost:5003",
            font=('Microsoft YaHei UI', 8),
            foreground='gray'
        ).pack(side=tk.RIGHT)
    
    def log_message(self, message, level='INFO'):
        """在日志区域显示消息"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {level}: {message}\n"
        
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)  # 自动滚动到底部
        self.log_text.config(state=tk.DISABLED)
        
        # 根据级别设置颜色
        if level == 'ERROR':
            # 高亮错误行
            pass  # tkinter scrolledtext不支持颜色,可以考虑使用其他组件
    
    def clear_log(self):
        """清空日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log_message("日志已清空")
    
    def export_log(self):
        """导出日志到文件"""
        from tkinter import filedialog
        
        log_dir = Path(__file__).parent / 'logs'
        log_dir.mkdir(exist_ok=True)
        
        filename = filedialog.asksaveasfilename(
            initialdir=log_dir,
            initialfile=f"server_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.get(1.0, tk.END))
                self.log_message(f"日志已导出到: {filename}")
            except Exception as e:
                self.log_message(f"导出日志失败: {str(e)}", 'ERROR')
                messagebox.showerror("错误", f"导出日志失败:\n{str(e)}")
    
    def start_fastapi(self):
        """启动FastAPI服务器"""
        if self.fastapi_running:
            messagebox.showwarning("警告", "FastAPI 服务已在运行")
            return
        
        try:
            self.log_message("正在启动 FastAPI 服务...")
            self.status_bar_label.config(text="正在启动 FastAPI...")
            
            # 在后台线程中启动
            threading.Thread(
                target=self._start_fastapi_thread,
                daemon=True
            ).start()
            
        except Exception as e:
            self.log_message(f"启动 FastAPI 失败: {str(e)}", 'ERROR')
            messagebox.showerror("错误", f"启动 FastAPI 失败:\n{str(e)}")
    
    def _start_fastapi_thread(self):
        """在后台线程中启动FastAPI"""
        try:
            # 获取项目根目录
            base_dir = Path(__file__).parent
            
            # 设置环境变量
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            
            # 启动命令 - 使用CREATE_NO_WINDOW标志隐藏控制台窗口
            cmd = [
                sys.executable, '-m', 'uvicorn',
                'fastapi_app.main:app',
                '--host', '0.0.0.0',
                '--port', '5002',
                '--log-level', 'info'
            ]
            
            # Windows平台使用CREATE_NO_WINDOW标志
            creationflags = 0
            if sys.platform == 'win32':
                creationflags = subprocess.CREATE_NO_WINDOW
            
            self.fastapi_process = subprocess.Popen(
                cmd,
                cwd=str(base_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                text=True,
                encoding='utf-8'
            )
            
            self.log_message(f"FastAPI 进程已启动 (PID: {self.fastapi_process.pid})")
            
            # 启动日志读取线程
            threading.Thread(
                target=self._read_fastapi_logs,
                args=(self.fastapi_process,),
                daemon=True
            ).start()
            
            # 等待服务就绪
            time.sleep(3)
            
            # 更新状态
            self.root.after(0, self._on_fastapi_started)
            
        except Exception as e:
            self.log_message(f"FastAPI 启动异常: {str(e)}", 'ERROR')
            self.root.after(0, lambda: self.status_bar_label.config(text="FastAPI 启动失败"))
    
    def _read_fastapi_logs(self, process):
        """读取FastAPI日志"""
        try:
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        self.root.after(0, lambda l=line: self.log_message(f"[FastAPI] {l}"))
        except Exception as e:
            self.log_message(f"读取 FastAPI 日志异常: {str(e)}", 'ERROR')
    
    def _on_fastapi_started(self):
        """FastAPI启动成功后的UI更新"""
        self.fastapi_running = True
        self.fastapi_status_label.config(text="● 运行中", foreground='green')
        if self.fastapi_process:
            self.fastapi_pid_label.config(text=f"PID: {self.fastapi_process.pid}")
        self.start_fastapi_btn.config(state=tk.DISABLED)
        self.stop_fastapi_btn.config(state=tk.NORMAL)
        self._update_start_all_button()
        self.status_bar_label.config(text="FastAPI 运行中")
        self.log_message("FastAPI 服务启动成功 - http://localhost:5002")
    
    def stop_fastapi(self):
        """停止FastAPI服务器"""
        if not self.fastapi_running or not self.fastapi_process:
            return
        
        try:
            self.log_message("正在停止 FastAPI 服务...")
            self.status_bar_label.config(text="正在停止 FastAPI...")
            
            # 优雅终止
            self.fastapi_process.terminate()
            try:
                self.fastapi_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # 强制终止
                self.fastapi_process.kill()
                self.fastapi_process.wait()
            
            self.log_message("FastAPI 服务已停止")
            self._on_fastapi_stopped()
            
        except Exception as e:
            self.log_message(f"停止 FastAPI 异常: {str(e)}", 'ERROR')
            messagebox.showerror("错误", f"停止 FastAPI 失败:\n{str(e)}")
    
    def _on_fastapi_stopped(self):
        """FastAPI停止成功后的UI更新"""
        self.fastapi_running = False
        self.fastapi_process = None
        self.fastapi_status_label.config(text="● 已停止", foreground='red')
        self.fastapi_pid_label.config(text="PID: -")
        self.start_fastapi_btn.config(state=tk.NORMAL)
        self.stop_fastapi_btn.config(state=tk.DISABLED)
        self._update_start_all_button()
        self._update_stop_all_button()
        self.status_bar_label.config(text="FastAPI 已停止")
    
    def start_flask(self):
        """启动Flask服务器"""
        if self.flask_running:
            messagebox.showwarning("警告", "Flask 服务已在运行")
            return
        
        try:
            self.log_message("正在启动 Flask 服务...")
            self.status_bar_label.config(text="正在启动 Flask...")
            
            threading.Thread(
                target=self._start_flask_thread,
                daemon=True
            ).start()
            
        except Exception as e:
            self.log_message(f"启动 Flask 失败: {str(e)}", 'ERROR')
            messagebox.showerror("错误", f"启动 Flask 失败:\n{str(e)}")
    
    def _start_flask_thread(self):
        """在后台线程中启动Flask"""
        try:
            base_dir = Path(__file__).parent
            
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            env['FLASK_ENV'] = 'production'
            
            # 启动Flask服务器 - 隐藏窗口
            cmd = [
                sys.executable, 'run_production_exe.py'
            ]
            
            creationflags = 0
            if sys.platform == 'win32':
                creationflags = subprocess.CREATE_NO_WINDOW
            
            self.flask_process = subprocess.Popen(
                cmd,
                cwd=str(base_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                text=True,
                encoding='utf-8'
            )
            
            self.log_message(f"Flask 进程已启动 (PID: {self.flask_process.pid})")
            
            threading.Thread(
                target=self._read_flask_logs,
                args=(self.flask_process,),
                daemon=True
            ).start()
            
            time.sleep(3)
            
            self.root.after(0, self._on_flask_started)
            
        except Exception as e:
            self.log_message(f"Flask 启动异常: {str(e)}", 'ERROR')
            self.root.after(0, lambda: self.status_bar_label.config(text="Flask 启动失败"))
    
    def _read_flask_logs(self, process):
        """读取Flask日志"""
        try:
            if process.stdout:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        self.root.after(0, lambda l=line: self.log_message(f"[Flask] {l}"))
        except Exception as e:
            self.log_message(f"读取 Flask 日志异常: {str(e)}", 'ERROR')
    
    def _on_flask_started(self):
        """Flask启动成功后的UI更新"""
        self.flask_running = True
        self.flask_status_label.config(text="● 运行中", foreground='green')
        if self.flask_process:
            self.flask_pid_label.config(text=f"PID: {self.flask_process.pid}")
        self.start_flask_btn.config(state=tk.DISABLED)
        self.stop_flask_btn.config(state=tk.NORMAL)
        self._update_start_all_button()
        self.status_bar_label.config(text="Flask 运行中")
        self.log_message("Flask 服务启动成功 - http://localhost:5003")
    
    def stop_flask(self):
        """停止Flask服务器"""
        if not self.flask_running or not self.flask_process:
            return
        
        try:
            self.log_message("正在停止 Flask 服务...")
            self.status_bar_label.config(text="正在停止 Flask...")
            
            self.flask_process.terminate()
            try:
                self.flask_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.flask_process.kill()
                self.flask_process.wait()
            
            self.log_message("Flask 服务已停止")
            self._on_flask_stopped()
            
        except Exception as e:
            self.log_message(f"停止 Flask 异常: {str(e)}", 'ERROR')
            messagebox.showerror("错误", f"停止 Flask 失败:\n{str(e)}")
    
    def _on_flask_stopped(self):
        """Flask停止成功后的UI更新"""
        self.flask_running = False
        self.flask_process = None
        self.flask_status_label.config(text="● 已停止", foreground='red')
        self.flask_pid_label.config(text="PID: -")
        self.start_flask_btn.config(state=tk.NORMAL)
        self.stop_flask_btn.config(state=tk.DISABLED)
        self._update_start_all_button()
        self._update_stop_all_button()
        self.status_bar_label.config(text="Flask 已停止")
    
    def start_all(self):
        """启动所有服务器"""
        self.log_message("正在启动所有服务器...")
        
        if not self.fastapi_running:
            self.start_fastapi()
            time.sleep(2)  # 等待FastAPI启动
        
        if not self.flask_running:
            self.start_flask()
    
    def stop_all(self):
        """停止所有服务器"""
        self.log_message("正在停止所有服务器...")
        
        if self.fastapi_running:
            self.stop_fastapi()
        
        if self.flask_running:
            self.stop_flask()
    
    def restart_all(self):
        """重启所有服务器"""
        self.log_message("正在重启所有服务器...")
        self.stop_all()
        time.sleep(2)
        self.start_all()
    
    def _update_start_all_button(self):
        """更新全部启动按钮状态"""
        if not self.fastapi_running or not self.flask_running:
            self.start_all_btn.config(state=tk.NORMAL)
        else:
            self.start_all_btn.config(state=tk.DISABLED)
    
    def _update_stop_all_button(self):
        """更新全部停止按钮状态"""
        if self.fastapi_running or self.flask_running:
            self.stop_all_btn.config(state=tk.NORMAL)
            self.restart_btn.config(state=tk.NORMAL)
        else:
            self.stop_all_btn.config(state=tk.DISABLED)
            self.restart_btn.config(state=tk.DISABLED)
    
    def check_server_status(self):
        """定期检查服务器进程状态"""
        # 检查FastAPI进程
        if self.fastapi_process:
            poll_result = self.fastapi_process.poll()
            if poll_result is not None:
                # 进程已终止
                if self.fastapi_running:
                    self.log_message(f"FastAPI 进程意外终止 (退出码: {poll_result})", 'ERROR')
                    self._on_fastapi_stopped()
                    messagebox.showwarning("警告", "FastAPI 服务意外停止,请检查日志")
        
        # 检查Flask进程
        if self.flask_process:
            poll_result = self.flask_process.poll()
            if poll_result is not None:
                if self.flask_running:
                    self.log_message(f"Flask 进程意外终止 (退出码: {poll_result})", 'ERROR')
                    self._on_flask_stopped()
                    messagebox.showwarning("警告", "Flask 服务意外停止,请检查日志")
        
        # 更新按钮状态
        self._update_start_all_button()
        self._update_stop_all_button()
        
        # 继续定时检查
        self.root.after(self.check_status_interval, self.check_server_status)
    
    def on_closing(self):
        """窗口关闭时的处理"""
        if self.fastapi_running or self.flask_running:
            result = messagebox.askyesnocancel(
                "确认退出",
                "服务器正在运行,是否在退出时停止所有服务器?\n\n"
                "是 - 停止服务器并退出\n"
                "否 - 不停止服务器,直接退出\n"
                "取消 - 取消退出"
            )
            
            if result is None:  # 取消
                return
            elif result:  # 是 - 停止服务器
                self.log_message("正在停止所有服务器...")
                self.stop_all()
                time.sleep(1)
        
        self.log_message("服务器管理器正在关闭...")
        self.root.destroy()


def main():
    """主入口函数"""
    try:
        root = tk.Tk()
        app = ServerManagerApp(root)
        root.mainloop()
    except Exception as e:
        print(f"[ERROR] 服务器管理器启动失败: {str(e)}")
        import traceback
        traceback.print_exc()
        input("按回车键退出...")
        sys.exit(1)


if __name__ == '__main__':
    main()
