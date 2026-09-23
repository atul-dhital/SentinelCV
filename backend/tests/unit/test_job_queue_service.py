from collections import deque

from services.job_queue_service import JobQueue, JobStatus, JobType


class FakeRedisBackend:
    def __init__(self):
        self.is_redis = True
        self._json_store = {}
        self._lists = {}

    def cache_set_json(self, key, value, ttl=None):
        self._json_store[key] = value
        return True

    def cache_get_json(self, key):
        return self._json_store.get(key)

    def list_right_push(self, key, value):
        self._lists.setdefault(key, deque()).append(value)
        return True

    def list_left_pop(self, key):
        queue = self._lists.setdefault(key, deque())
        if not queue:
            return None
        return queue.popleft()

    def list_remove(self, key, value, count=0):
        queue = self._lists.setdefault(key, deque())
        removed = 0
        retained = deque()
        while queue:
            item = queue.popleft()
            if str(item) == str(value) and (count == 0 or removed < abs(count)):
                removed += 1
                continue
            retained.append(item)
        self._lists[key] = retained
        return removed

    def list_length(self, key):
        return len(self._lists.setdefault(key, deque()))


def _fresh_queue(redis_backend=None):
    queue = JobQueue()
    queue._redis = redis_backend
    queue._queue.clear()
    queue._jobs.clear()
    return queue


def test_job_queue_in_memory_lifecycle():
    queue = _fresh_queue(redis_backend=None)

    job = queue.enqueue(
        JobType.REPORT_GENERATION,
        {"report_type": "daily"},
        organization_id="org-1",
        user_id="user-1",
    )

    assert queue.queue_size() == 1
    assert queue.get_stats()["backend"] == "in-memory"

    dequeued = queue.dequeue()
    assert dequeued is not None
    assert dequeued.id == job.id
    assert dequeued.status == JobStatus.RUNNING

    queue.update_progress(job.id, 42.5)
    queue.complete_job(job.id, result={"artifact": "daily.pdf"})

    status = queue.get_job_status(job.id)
    assert status is not None
    assert status["status"] == JobStatus.COMPLETED
    assert status["progress"] == 100.0
    assert status["result"]["artifact"] == "daily.pdf"


def test_job_queue_redis_backend_persists_across_instances():
    redis_backend = FakeRedisBackend()
    producer = _fresh_queue(redis_backend=redis_backend)

    job = producer.enqueue(
        JobType.MODEL_TRAINING,
        {"model": "vit"},
        organization_id="org-2",
        user_id="trainer-1",
    )

    consumer = _fresh_queue(redis_backend=redis_backend)

    assert consumer.queue_size() == 1
    listed = consumer.list_jobs(organization_id="org-2")
    assert len(listed) == 1
    assert listed[0]["id"] == job.id
    assert listed[0]["status"] == JobStatus.QUEUED

    dequeued = consumer.dequeue()
    assert dequeued is not None
    assert dequeued.id == job.id
    assert dequeued.status == JobStatus.RUNNING

    consumer.fail_job(job.id, "worker_error")
    refreshed = producer.get_job_status(job.id)
    assert refreshed is not None
    assert refreshed["status"] == JobStatus.FAILED
    assert refreshed["error"] == "worker_error"
    assert consumer.get_stats()["backend"] == "redis"


def test_job_queue_cancel_removes_redis_pending_item():
    redis_backend = FakeRedisBackend()
    queue = _fresh_queue(redis_backend=redis_backend)

    job = queue.enqueue(
        JobType.EXPORT_MODEL,
        {"target": "onnx"},
        organization_id="org-3",
    )

    assert queue.queue_size() == 1
    assert queue.cancel_job(job.id) is True
    assert queue.queue_size() == 0

    status = queue.get_job_status(job.id)
    assert status is not None
    assert status["status"] == JobStatus.CANCELLED
