// Streaming data pipelines into Bigtable

// step1: Clone the repo
// git clone https://github.com/GoogleCloudPlatform/training-data-analyst

// step2: set env variables
// source /training/project_env.sh

// step3: Prepare Hbase quickstart files
// cd ~/training-data-analyst/courses/streaming/process/sandiego
// ./install_quickstart.sh

// step4: Simulate traffic data into pubsub
// Reads sample data from csv and publishes to pubsub
// /training/sensor_magic.sh

// step5: Start a second ssh terminal for rest of the task(Set env variables again)

// step6: Review setup for dataflow pipeline
// gcloud services disable dataflow.googleapis.com --force
// gcloud services enable dataflow.googleapis.com

// cd ~/training-data-analyst/courses/streaming/process/sandiego

// nano run_oncloud.sh

// The script takes 3 required arguments: project id, bucket name, classname and possibly a 4th argument: options.
// In this part of the lab, we will use the --bigtable option which will direct the pipeline to write into Cloud Bigtable.

// step7: Create a bigtable instance

// cd ~/training-data-analyst/courses/streaming/process/sandiego
// export ZONE=us-east1-c

// ./create_cbt.sh

// step8: Run the dataflow pipeline
// cd ~/training-data-analyst/courses/streaming/process/sandiego
// export REGION=us-east1

// ./run_oncloud.sh $DEVSHELL_PROJECT_ID $BUCKET CurrentConditions --bigtable

// step9: test the pipeline (Query Bigtable)
// cd ~/training-data-analyst/courses/streaming/process/sandiego/quickstart

// ./quickstart.sh

// hbase> scan 'current_conditions', {'LIMIT' => 2}
// hbase> scan 'current_conditions', {'LIMIT' => 10, STARTROW => '15#S#1', ENDROW => '15#S#999', COLUMN => 'lane:speed'}
// hbase> quit

//code - currentconditions.java


package com.google.cloud.training.dataanalyst.sandiego;

import java.util.ArrayList;
import java.util.List;

import org.apache.beam.runners.dataflow.options.DataflowPipelineOptions;
import org.apache.beam.sdk.Pipeline;
import org.apache.beam.sdk.io.gcp.bigquery.BigQueryIO;
import org.apache.beam.sdk.io.gcp.pubsub.PubsubIO;
import org.apache.beam.sdk.options.Default;
import org.apache.beam.sdk.options.Description;
import org.apache.beam.sdk.options.PipelineOptionsFactory;
import org.apache.beam.sdk.transforms.DoFn;
import org.apache.beam.sdk.transforms.ParDo;
import org.apache.beam.sdk.values.PCollection;

import com.google.api.services.bigquery.model.TableFieldSchema;
import com.google.api.services.bigquery.model.TableRow;
import com.google.api.services.bigquery.model.TableSchema;

/**
 * A dataflow pipeline that pulls from Pub/Sub and writes to BigQuery
 * 
 * @author pkumari
 *
 */
@SuppressWarnings("serial")
public class CurrentConditions {

  public static interface MyOptions extends DataflowPipelineOptions {
    @Description("Also stream to Bigtable?")
    @Default.Boolean(false)
    boolean getBigtable();

    void setBigtable(boolean b);
  }

  public static void main(String[] args) {
    MyOptions options = PipelineOptionsFactory.fromArgs(args).withValidation().as(MyOptions.class);
    options.setStreaming(true);
    Pipeline p = Pipeline.create(options);

    String topic = "projects/" + options.getProject() + "/topics/sandiego";
    String currConditionsTable = options.getProject() + ":demos.current_conditions";

    // Build the table schema for the output table.
    List<TableFieldSchema> fields = new ArrayList<>();
    fields.add(new TableFieldSchema().setName("timestamp").setType("TIMESTAMP"));
    fields.add(new TableFieldSchema().setName("latitude").setType("FLOAT"));
    fields.add(new TableFieldSchema().setName("longitude").setType("FLOAT"));
    fields.add(new TableFieldSchema().setName("highway").setType("STRING"));
    fields.add(new TableFieldSchema().setName("direction").setType("STRING"));
    fields.add(new TableFieldSchema().setName("lane").setType("INTEGER"));
    fields.add(new TableFieldSchema().setName("speed").setType("FLOAT"));
    fields.add(new TableFieldSchema().setName("sensorId").setType("STRING"));
    TableSchema schema = new TableSchema().setFields(fields);

    PCollection<LaneInfo> currentConditions = p //
        .apply("GetMessages", PubsubIO.readStrings().fromTopic(topic)) //
        .apply("ExtractData", ParDo.of(new DoFn<String, LaneInfo>() {
          @ProcessElement
          public void processElement(ProcessContext c) throws Exception {
            String line = c.element();
            c.output(LaneInfo.newLaneInfo(line));
          }
        }));

    if (options.getBigtable()) {
      BigtableHelper.writeToBigtable(currentConditions, options);
    }

    currentConditions.apply("ToBQRow", ParDo.of(new DoFn<LaneInfo, TableRow>() {
      @ProcessElement
      public void processElement(ProcessContext c) throws Exception {
        TableRow row = new TableRow();
        LaneInfo info = c.element();
        row.set("timestamp", info.getTimestamp());
        row.set("latitude", info.getLatitude());
        row.set("longitude", info.getLongitude());
        row.set("highway", info.getHighway());
        row.set("direction", info.getDirection());
        row.set("lane", info.getLane());
        row.set("speed", info.getSpeed());
        row.set("sensorId", info.getSensorKey());
        c.output(row);
      }
    })) //
        .apply(BigQueryIO.writeTableRows().to(currConditionsTable)//
            .withSchema(schema)//
            .withWriteDisposition(BigQueryIO.Write.WriteDisposition.WRITE_APPEND)
            .withCreateDisposition(BigQueryIO.Write.CreateDisposition.CREATE_IF_NEEDED));

    p.run();
  }
}
