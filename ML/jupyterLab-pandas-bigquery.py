#Bigquery in JupyterLab/Plot using pandas

#Using magic function

---------------------------1st cell----------------------

%%bigquery df --use_rest_api
SELECT
  depdelay as departure_delay,
  COUNT(1) AS num_flights,
  APPROX_QUANTILES(arrdelay, 10) AS arrival_delay_deciles
FROM
  `cloud-training-demos.airline_ontime_data.flights`
WHERE
 depdelay is not null
GROUP BY
  depdelay
HAVING
  num_flights > 100
ORDER BY
  depdelay ASC
  
#--------------------------------------------------------------
  
  df.head()
#-------------------------------------------------------------------
  
#Make a plot with pandas

import pandas as pd

percentiles = df['arrival_delay_deciles'].apply(pd.Series)
percentiles.rename(columns = lambda x : '{0}%'.format(x*10), inplace=True)
percentiles.head()

#------------------------------------------------------------------------

df = pd.concat([df['departure_delay'], percentiles], axis=1)
df.head()

#---------------------------------------------------------

df.drop(labels=['0%', '100%'], axis=1, inplace=True)
df.plot(x='departure_delay', xlim=(-30,50), ylim=(-50,50));


