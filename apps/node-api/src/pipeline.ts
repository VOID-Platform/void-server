import IORedis from 'ioredis';

export type PipelineStage =
  | 'TRACE_RECEIVED'
  | 'RISK_ENGINE'
  | 'INCIDENT_CREATED'
  | 'EVALUATOR'
  | 'PROMOTION_GATE'
  | 'ISSUE_AGENT'
  | 'COMPLETED';

export type StageStatus = 'running' | 'completed' | 'failed';

export type IssueAgentSubStep =
  | 'BUILDING_TIMELINE'
  | 'SEARCHING_REPOSITORY'
  | 'READING_FILES'
  | 'EXTRACTING_FUNCTIONS'
  | 'VALIDATING_EVIDENCE'
  | 'GENERATING_REPORT'
  | 'CREATING_GITHUB_ISSUE';

export interface PipelineEvent {
  incidentId: string;
  stage: PipelineStage;
  status: StageStatus;
  detail?: string;
  subStep?: IssueAgentSubStep;
  timestamp: string;
}

export function createPipelinePublisher(redisUrl: string) {
  const publisher = new IORedis(redisUrl);

  return {
    publish(event: PipelineEvent) {
      const channel = `pipeline:${event.incidentId}`;
      const message = JSON.stringify(event);
      return publisher.publish(channel, message).catch((err) => {
        console.error(`[pipeline] publish error: ${err}`);
      });
    },

    async stage(incidentId: string, stage: PipelineStage, status: StageStatus, detail?: string) {
      await this.publish({
        incidentId,
        stage,
        status,
        detail,
        timestamp: new Date().toISOString(),
      });
    },

    async subStep(incidentId: string, subStep: IssueAgentSubStep, detail?: string) {
      await this.publish({
        incidentId,
        stage: 'ISSUE_AGENT',
        status: 'running',
        subStep,
        detail,
        timestamp: new Date().toISOString(),
      });
    },

    quit() {
      return publisher.quit();
    },
  };
}

export function createPipelineSubscriber(redisUrl: string) {
  const subscriber = new IORedis(redisUrl);

  return {
    subscribe(incidentId: string, callback: (event: PipelineEvent) => void) {
      const channel = `pipeline:${incidentId}`;
      subscriber.subscribe(channel);
      subscriber.on('message', (_ch, message) => {
        if (_ch === channel) {
          try {
            const event: PipelineEvent = JSON.parse(message);
            callback(event);
          } catch {
            console.error(`[pipeline] parse error for message: ${message}`);
          }
        }
      });
    },

    unsubscribe(incidentId: string) {
      subscriber.unsubscribe(`pipeline:${incidentId}`);
    },

    quit() {
      return subscriber.quit();
    },
  };
}
