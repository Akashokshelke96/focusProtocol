"""Bound this application's processes and observe host pressure without changing quality."""
import os
import subprocess
import time
import psutil
from app.utils.ffmpeg import no_window_flags


def gpu_sample():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu',
                                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3,
                                **no_window_flags())
        name, used, total, utilization, temperature = result.stdout.splitlines()[0].split(', ')
        return dict(name=name, vram_mb=float(used), vram_total_mb=float(total), utilization=float(utilization), temperature_c=float(temperature))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {}


def constrain(process, cores):
    try:
        allowed = process.cpu_affinity()
        process.cpu_affinity(allowed[:min(cores, len(allowed))])
        if os.name == 'nt':
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        return True
    except (psutil.Error, AttributeError):
        return False


class ResourceMonitor:
    def __init__(self, pid, settings):
        self.settings = settings
        self.process = psutil.Process(pid)
        self.constrained = constrain(self.process, settings.render_cpu_threads)
        self.process.cpu_percent()
        self.high_since = None
        self.samples = []
        self.throttled = False

    def sample(self):
        ram = psutil.virtual_memory()
        gpu = gpu_sample()
        sample = dict(cpu_percent=psutil.cpu_percent(), ram_percent=ram.percent,
                      available_ram_mb=round(ram.available/2**20), gpu=gpu)
        try:
            sample.update(process_cpu_percent=self.process.cpu_percent(), process_ram_mb=round(self.process.memory_info().rss/2**20))
        except psutil.Error:
            pass
        hot = sample['cpu_percent'] >= self.settings.render_cpu_high_percent or ram.percent >= 95 or gpu.get('temperature_c', 0) >= self.settings.render_gpu_max_temperature - 5
        self.high_since = (self.high_since or time.monotonic()) if hot else None
        if self.high_since and time.monotonic() - self.high_since >= self.settings.render_pressure_seconds:
            self.throttled = constrain(self.process, 1)
        sample['cpu_limited'] = self.constrained
        sample['pressure_throttled'] = self.throttled
        self.samples.append(sample)
        # Bounded statistics, never accumulate hours of per-frame samples.
        self.samples = self.samples[-720:]
        return sample

    def summary(self):
        result = dict(samples=len(self.samples), cpu_limited=self.constrained, pressure_throttled=self.throttled)
        for key in ('cpu_percent', 'ram_percent', 'process_cpu_percent', 'process_ram_mb'):
            values = [s[key] for s in self.samples if key in s]
            if values:
                result[key] = dict(average=round(sum(values)/len(values), 2), peak=max(values))
        for key in ('utilization', 'vram_mb', 'temperature_c'):
            values = [s['gpu'][key] for s in self.samples if key in s['gpu']]
            if values:
                result['gpu_' + key] = dict(average=round(sum(values)/len(values), 2), peak=max(values))
        return result
