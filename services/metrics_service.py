import time
import threading

class MetricsTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "search_latency": [],        # List of times in seconds
            "routing_success": 0,       # Successful function calls
            "routing_total": 0,         # Total AI requests
            "transcription_chars": 0,    # Total characters transcribed
            "transcription_time": 0.0,   # Total time spent transcribing
            "files_indexed": 0
        }

    def record_search(self, duration):
        with self.lock:
            self.data["search_latency"].append(duration)
            # Keep only last 50 samples for moving average
            if len(self.data["search_latency"]) > 50:
                self.data["search_latency"].pop(0)

    def record_routing(self, was_successful):
        with self.lock:
            self.data["routing_total"] += 1
            if was_successful:
                self.data["routing_success"] += 1

    def record_transcription(self, char_count, duration):
        with self.lock:
            self.data["transcription_chars"] += char_count
            self.data["transcription_time"] += duration

    def record_indexing(self):
        with self.lock:
            self.data["files_indexed"] += 1

    def get_report(self):
        with self.lock:
            avg_latency = (sum(self.data["search_latency"]) / len(self.data["search_latency"])) * 1000 if self.data["search_latency"] else 0
            routing_rate = (self.data["routing_success"] / self.data["routing_total"]) * 100 if self.data["routing_total"] > 0 else 100
            
            # Transcription Efficiency (Chars per second)
            trans_eff = (self.data["transcription_chars"] / self.data["transcription_time"]) if self.data["transcription_time"] > 0 else 0
            
            return {
                "search_latency_ms": round(avg_latency, 2),
                "routing_reliability": round(routing_rate, 1),
                "transcription_speed": round(trans_eff, 1),
                "files_processed": self.data["files_indexed"]
            }

# Singleton instance
tracker = MetricsTracker()
