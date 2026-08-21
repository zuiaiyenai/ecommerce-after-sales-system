"""Transport entry points for the Agent service.

``http_server`` exposes the synchronous chat/SSE/emotion/vision/knowledge
endpoints; ``kafka_adapter`` consumes the asynchronous formal-review
events from Kafka. This package is the outermost layer — it depends on
``application`` and never on lower layers' concrete infrastructure.
"""
