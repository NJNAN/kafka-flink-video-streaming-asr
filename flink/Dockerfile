FROM apache/flink:1.18.1-scala_2.12-java17

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip curl \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Flink 默认不带 Kafka connector，这里放入 lib，PyFlink 才能读写 Kafka。
RUN curl -L -o /opt/flink/lib/flink-sql-connector-kafka-3.1.0-1.18.jar \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.1.0-1.18/flink-sql-connector-kafka-3.1.0-1.18.jar

COPY transcription_job.py /opt/flink/usrlib/transcription_job.py
COPY wait-for.sh /opt/flink/usrlib/wait-for.sh

RUN chmod +x /opt/flink/usrlib/wait-for.sh

USER flink
