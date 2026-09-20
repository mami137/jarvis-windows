"""
Thread-safe Jarvis own-network byte counters.
Yalnızca JARVIS'in kendi gönderdiği/aladığı gerçek veriyi sayar.
"""

import threading

_lock = threading.Lock()
_sent_total = 0.0
_recv_total = 0.0


def add_sent(n):
    global _sent_total
    if n and n > 0:
        with _lock:
            _sent_total += n


def add_recv(n):
    global _recv_total
    if n and n > 0:
        with _lock:
            _recv_total += n


def totals():
    with _lock:
        return _sent_total, _recv_total


def reset():
    global _sent_total, _recv_total
    with _lock:
        _sent_total = 0.0
        _recv_total = 0.0