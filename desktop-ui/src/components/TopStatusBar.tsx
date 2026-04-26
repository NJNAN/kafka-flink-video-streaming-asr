import type { ServiceStatus } from "../types";

interface TopStatusBarProps {
  services: ServiceStatus[];
}

export function TopStatusBar({ services }: TopStatusBarProps) {
  return (
    <header className="top-status-bar">
      <div className="brand-plaque">
        <div className="brand-mark">SS</div>
        <div>
          <h1>StreamSense</h1>
          <p>视频语音理解工作台</p>
        </div>
      </div>

      <div className="service-lights" aria-label="服务状态">
        {services.map((service) => (
          <div className="service-light" key={service.name} title={`${service.name}: ${service.headline}`}>
            <span className={`lamp lamp-${service.state}`} />
            <span>{service.name}</span>
          </div>
        ))}
      </div>
    </header>
  );
}
