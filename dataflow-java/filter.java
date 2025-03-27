// step0:
// git clone https://github.com/GoogleCloudPlatform/training-data-analyst

// BUCKET="PROJECT_ID"
// echo $BUCKET

// REGION="us-central1"
// echo $REGION

// step1:
// cd ~/training-data-analyst/courses/data_analysis/lab2

// step2:
// mvn archetype:generate \
//   -DarchetypeArtifactId=google-cloud-dataflow-java-archetypes-starter \
//   -DarchetypeGroupId=com.google.cloud.dataflow \
//   -DgroupId=com.example.pipelinesrus.newidea \
//   -DartifactId=newidea \
//   -Dversion="[1.0.0,2.0.0]" \
//   -DinteractiveMode=false
  
// step3: to run below code
// #!/bin/bash

// if [ "$#" -ne 4 ]; then
//    echo "Usage:   ./run_oncloud.sh project-name  bucket-name  mainclass-basename"
//    echo "Example: ./run_oncloud.sh cloud-training-demos  cloud-training-demos  JavaProjectsThatNeedHelp"
//    exit
// fi

// PROJECT=$1
// BUCKET=$2
// MAIN=com.google.cloud.training.dataanalyst.javahelp.$3
// REGION=$4

// echo "project=$PROJECT  bucket=$BUCKET  main=$MAIN region=$REGION"

// export PATH=/usr/lib/jvm/java-8-openjdk-amd64/bin/:$PATH
// mvn compile -e exec:java \
//  -Dexec.mainClass=$MAIN \
//       -Dexec.args="--project=$PROJECT \
//       --stagingLocation=gs://$BUCKET/staging/ \
//       --tempLocation=gs://$BUCKET/staging/ \
//       --region=$REGION \
//       --workerMachineType=e2-standard-2 \
//       --runner=DataflowRunner"

// step4:
// java code 

/*
 * Copyright (C) 2016 Google Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy of
 * the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
 * License for the specific language governing permissions and limitations under
 * the License.
 */

package com.google.cloud.training.dataanalyst.javahelp;

import org.apache.beam.sdk.Pipeline;
import org.apache.beam.sdk.io.TextIO;
import org.apache.beam.sdk.options.PipelineOptions;
import org.apache.beam.sdk.options.PipelineOptionsFactory;
import org.apache.beam.sdk.transforms.DoFn;
import org.apache.beam.sdk.transforms.ParDo;

/**
 * A dataflow pipeline that prints the lines that match a specific search term
 * 
 * @author vlakshmanan
 *
 */
public class Grep {

	@SuppressWarnings("serial")
	public static void main(String[] args) {
		PipelineOptions options = PipelineOptionsFactory.fromArgs(args).withValidation().create();
		Pipeline p = Pipeline.create(options);

		String input = "gs://qwiklabs-gcp-03-7a58325e97a5-bucket/javahelp/*.java";
		String outputPrefix = "gs://qwiklabs-gcp-03-7a58325e97a5-bucket/javahelp/output";
		final String searchTerm = "import";

		p //
				.apply("GetJava", TextIO.read().from(input)) //
				.apply("Grep", ParDo.of(new DoFn<String, String>() {
					@ProcessElement
					public void processElement(ProcessContext c) throws Exception {
						String line = c.element();
						if (line.contains(searchTerm)) {
							c.output(line);
						}
					}
				})) //
				.apply(TextIO.write().to(outputPrefix).withSuffix(".txt").withoutSharding());

		p.run();
	}
}
