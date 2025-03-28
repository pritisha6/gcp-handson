// Java - Execute a Dataflow pipeline that can carry out Map and Reduce operations, use side inputs, and stream into BigQuery.

// step1: git clone https://github.com/GoogleCloudPlatform/training-data-analyst

// step2: Dataflow APi is succesfully enabled

// gcloud services disable dataflow.googleapis.com --force
// gcloud services enable dataflow.googleapis.com

// step3: set environment variables

// PROJECT="qwiklabs-gcp-02-31fcb8c43a7a"
// echo $PROJECT

// BUCKET="qwiklabs-gcp-02-31fcb8c43a7a"
// echo $BUCKET

// REGION="us-east1"
// echo $REGION

// step4: How to execute the code?
// cd ~/training-data-analyst/courses/data_analysis/lab2/javahelp
// ./run_oncloud3.sh $PROJECT $BUCKET JavaProjectsThatNeedHelp $REGION

// step5: Test the output
// BUCKET="qwiklabs-gcp-02-31fcb8c43a7a"
// gcloud storage cp gs://$BUCKET/javahelp/output.csv .
// head output.csv

// step6: Code

package com.google.cloud.training.dataanalyst.javahelp;

import java.util.ArrayList;
import java.util.List;

import org.apache.beam.sdk.Pipeline;
import org.apache.beam.sdk.io.TextIO;
import org.apache.beam.sdk.options.Default;
import org.apache.beam.sdk.options.Description;
import org.apache.beam.sdk.options.PipelineOptions;
import org.apache.beam.sdk.options.PipelineOptionsFactory;
import org.apache.beam.sdk.transforms.DoFn;
import org.apache.beam.sdk.transforms.ParDo;
import org.apache.beam.sdk.transforms.Sum;
import org.apache.beam.sdk.transforms.Top;
import org.apache.beam.sdk.values.KV;

/**
 * A dataflow pipeline that finds the most commonly imported packages
 * 
 * @author vlakshmanan
 *
 */
public class IsPopular {

	public static interface MyOptions extends PipelineOptions {
		@Description("Output prefix")
		@Default.String("/tmp/output")
		String getOutputPrefix();

		void setOutputPrefix(String s);
		
		@Description("Input directory")
		@Default.String("src/main/java/com/google/cloud/training/dataanalyst/javahelp/")
		String getInput();

		void setInput(String s);
	}
	
	@SuppressWarnings("serial")
	public static void main(String[] args) {
		MyOptions options = PipelineOptionsFactory.fromArgs(args).withValidation().as(MyOptions.class);
		Pipeline p = Pipeline.create(options);

		String input = options.getInput() + "*.java";
		String outputPrefix = options.getOutputPrefix();
		final String keyword = "import";
		
		p //
				.apply("GetJava", TextIO.read().from(input)) //
				.apply("GetImports", ParDo.of(new DoFn<String, String>() {
					@ProcessElement
					public void processElement(ProcessContext c) throws Exception {
						String line = c.element();
						if (line.startsWith(keyword)) {
							c.output(line);
						}
					}
				})) //
				.apply("PackageUse", ParDo.of(new DoFn<String, KV<String,Integer>>() {
					@ProcessElement
					public void processElement(ProcessContext c) throws Exception {
						List<String> packages = getPackages(c.element(), keyword);
						for (String p : packages) {
							c.output(KV.of(p, 1));
						}
					}
				})) //
				.apply(Sum.integersPerKey())
				.apply("Top_5", Top.of(5, new KV.OrderByValue<>())) //
				.apply("ToString", ParDo.of(new DoFn<List<KV<String, Integer>>, String>() {

					@ProcessElement
					public void processElement(ProcessContext c) throws Exception {
						StringBuffer sb = new StringBuffer();
						for (KV<String, Integer> kv : c.element()) {
							sb.append(kv.getKey() + "," + kv.getValue() + '\n');
						}
						c.output(sb.toString());
					}

				})) //
				.apply(TextIO.write().to(outputPrefix).withSuffix(".csv").withoutSharding());

		p.run();
	}
	
	private static List<String> getPackages(String line, String keyword) {
		int start = line.indexOf(keyword) + keyword.length();
		int end = line.indexOf(";", start);
		if (start < end) {
			String packageName = line.substring(start, end).trim();
			return splitPackageName(packageName);
		}
		return new ArrayList<String>();
	}
	
	private static List<String> splitPackageName(String packageName) {
		// e.g. given com.example.appname.library.widgetname
		// returns com
		// com.example
		// com.example.appname
		// etc.
		List<String> result = new ArrayList<>();
		int end = packageName.indexOf('.');
		while (end > 0) {
			result.add(packageName.substring(0, end));
			end = packageName.indexOf('.', end + 1);
		}
		result.add(packageName);
		return result;
	}
}
