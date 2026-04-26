import type { LogLine, ServiceStatus } from "../types";

interface ServiceMonitorPanelProps {
  services: ServiceStatus[];
  logs: LogLine[];
  compact?: boolean;
}

export function ServiceMonitorPanel({ services, logs, compact = false }: ServiceMonitorPanelProps) {
  return (
    <section className={`service-monitor ${compact ? "is-compact" : ""}`}>
      <div className="monitor-head">
        <h2>系统仪表盘</h2>
        <p>Kafka / Flink / ASR / Redis / API</p>
      </div>

      <div className="service-gauge-grid">
        {services.map((service) => (
          <article className={`service-gauge gauge-${service.state}`} key={service.name}>
            <div className="gauge-face">
              <span className={`lamp lamp-${service.state}`} />
              <strong>{service.name}</strong>
              <small>{service.headline}</small>
            </div>
            <dl>
              {Object.entries(service.metrics).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
              {service.latencyMs !== undefined && (
                <div>
                  <dt>latency</dt>
                  <dd>{service.latencyMs}ms</dd>
                </div>
              )}
            </dl>
          </article>
        ))}
      </div>

      <div className="message-flow">
        <div className="engraved-subheading">消息流</div>
        <div className="flow-strip">
          <span>audio-segment</span>
          <i />
          <span>transcription-result</span>
          <i />
          <span>keyword-event</span>
          <i />
          <span>results</span>
        </div>
      </div>

      <div className="monitor-lcd">
        {logs.map((line) => (
          <p key={line.id}>
            <span>{line.time}</span> [{line.level}] {line.source}: {line.message}
          </p>
        ))}
      </div>
    </section>
  );
}
