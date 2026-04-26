import type { BackendHealth, ComposeContainer, LogLine, ServiceStatus } from "../types";

interface ServiceMonitorPanelProps {
  services: ServiceStatus[];
  logs: LogLine[];
  compact?: boolean;
  compose?: ComposeContainer[];
  backendHealth?: BackendHealth | null;
}

export function ServiceMonitorPanel({ services, logs, compact = false, compose = [], backendHealth }: ServiceMonitorPanelProps) {
  return (
    <section className={`service-monitor ${compact ? "is-compact" : ""}`}>
      <div className="monitor-head">
        <h2>系统仪表盘</h2>
        <p>Kafka / Flink / ASR / Redis / API</p>
      </div>

      <div className="service-gauge-grid">
        {compose.length > 0 && (
          <article className="service-gauge gauge-busy">
            <div className="gauge-face">
              <span className="lamp lamp-busy" />
              <strong>Docker</strong>
              <small>{compose.length} containers</small>
            </div>
            <dl>
              {compose.slice(0, 6).map((container) => (
                <div key={`${container.name}-${container.service}`}>
                  <dt>{container.service || container.name}</dt>
                  <dd>{container.state || container.status || "unknown"}</dd>
                </div>
              ))}
            </dl>
          </article>
        )}
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
          <span>hotword updates</span>
          <i />
          <span>{backendHealth ? `health ${backendHealth.api}/${backendHealth.asr}/${backendHealth.flink}` : "results"}</span>
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
