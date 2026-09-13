"""Largest cities per US state (plus DC), by approximate population.

Google Maps returns at most ~120 results per search, so nationwide coverage
comes from many city-level searches rather than one per state. Five per
state is the default tier; extend a state's list to go deeper there.
"""

USA_CITIES = {
    "AL": ["Birmingham", "Huntsville", "Montgomery", "Mobile", "Tuscaloosa"],
    "AK": ["Anchorage", "Fairbanks", "Juneau", "Wasilla", "Sitka"],
    "AZ": ["Phoenix", "Tucson", "Mesa", "Chandler", "Scottsdale"],
    "AR": ["Little Rock", "Fayetteville", "Fort Smith", "Springdale", "Jonesboro"],
    "CA": ["Los Angeles", "San Diego", "San Jose", "San Francisco", "Fresno"],
    "CO": ["Denver", "Colorado Springs", "Aurora", "Fort Collins", "Lakewood"],
    "CT": ["Bridgeport", "Stamford", "New Haven", "Hartford", "Waterbury"],
    "DE": ["Wilmington", "Dover", "Newark", "Middletown", "Smyrna"],
    "DC": ["Washington"],
    "FL": ["Jacksonville", "Miami", "Tampa", "Orlando", "St. Petersburg"],
    "GA": ["Atlanta", "Columbus", "Augusta", "Macon", "Savannah"],
    "HI": ["Honolulu", "Hilo", "Kailua", "Kapolei", "Pearl City"],
    "ID": ["Boise", "Meridian", "Nampa", "Idaho Falls", "Coeur d'Alene"],
    "IL": ["Chicago", "Aurora", "Naperville", "Joliet", "Rockford"],
    "IN": ["Indianapolis", "Fort Wayne", "Evansville", "South Bend", "Carmel"],
    "IA": ["Des Moines", "Cedar Rapids", "Davenport", "Sioux City", "Iowa City"],
    "KS": ["Wichita", "Overland Park", "Kansas City", "Olathe", "Topeka"],
    "KY": ["Louisville", "Lexington", "Bowling Green", "Owensboro", "Covington"],
    "LA": ["New Orleans", "Baton Rouge", "Shreveport", "Lafayette", "Lake Charles"],
    "ME": ["Portland", "Lewiston", "Bangor", "South Portland", "Auburn"],
    "MD": ["Baltimore", "Columbia", "Germantown", "Silver Spring", "Frederick"],
    "MA": ["Boston", "Worcester", "Springfield", "Cambridge", "Lowell"],
    "MI": ["Detroit", "Grand Rapids", "Warren", "Sterling Heights", "Ann Arbor"],
    "MN": ["Minneapolis", "Saint Paul", "Rochester", "Duluth", "Bloomington"],
    "MS": ["Jackson", "Gulfport", "Southaven", "Hattiesburg", "Biloxi"],
    "MO": ["Kansas City", "St. Louis", "Springfield", "Columbia", "Independence"],
    "MT": ["Billings", "Missoula", "Great Falls", "Bozeman", "Helena"],
    "NE": ["Omaha", "Lincoln", "Bellevue", "Grand Island", "Kearney"],
    "NV": ["Las Vegas", "Henderson", "Reno", "North Las Vegas", "Sparks"],
    "NH": ["Manchester", "Nashua", "Concord", "Dover", "Portsmouth"],
    "NJ": ["Newark", "Jersey City", "Paterson", "Elizabeth", "Edison"],
    "NM": ["Albuquerque", "Las Cruces", "Rio Rancho", "Santa Fe", "Roswell"],
    "NY": ["New York", "Buffalo", "Rochester", "Yonkers", "Syracuse"],
    "NC": ["Charlotte", "Raleigh", "Greensboro", "Durham", "Winston-Salem"],
    "ND": ["Fargo", "Bismarck", "Grand Forks", "Minot", "West Fargo"],
    "OH": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Akron"],
    "OK": ["Oklahoma City", "Tulsa", "Norman", "Broken Arrow", "Edmond"],
    "OR": ["Portland", "Salem", "Eugene", "Gresham", "Hillsboro"],
    "PA": ["Philadelphia", "Pittsburgh", "Allentown", "Reading", "Erie"],
    "RI": ["Providence", "Warwick", "Cranston", "Pawtucket", "East Providence"],
    "SC": ["Charleston", "Columbia", "North Charleston", "Mount Pleasant", "Greenville"],
    "SD": ["Sioux Falls", "Rapid City", "Aberdeen", "Brookings", "Watertown"],
    "TN": ["Nashville", "Memphis", "Knoxville", "Chattanooga", "Clarksville"],
    "TX": ["Houston", "San Antonio", "Dallas", "Austin", "Fort Worth"],
    "UT": ["Salt Lake City", "West Valley City", "Provo", "West Jordan", "Orem"],
    "VT": ["Burlington", "South Burlington", "Rutland", "Essex Junction", "Barre"],
    "VA": ["Virginia Beach", "Chesapeake", "Norfolk", "Richmond", "Arlington"],
    "WA": ["Seattle", "Spokane", "Tacoma", "Vancouver", "Bellevue"],
    "WV": ["Charleston", "Huntington", "Morgantown", "Parkersburg", "Wheeling"],
    "WI": ["Milwaukee", "Madison", "Green Bay", "Kenosha", "Racine"],
    "WY": ["Cheyenne", "Casper", "Laramie", "Gillette", "Rock Springs"],
}

# Same five verticals as the first US batch.
VERTICALS = ["dentist", "aesthetics clinic", "beauty salon", "real estate agent"]

# Already scraped into usa_leads_master.csv by run_batch_usa.sh.
ALREADY_DONE = {("Miami", "FL"), ("Houston", "TX"), ("Dallas", "TX"),
                ("Los Angeles", "CA"), ("New York", "NY")}

# Nationally famous metros only — the cut the user asked for instead of
# 5-per-state coverage. Roughly the 35 biggest/best-known US cities.
FAMOUS_CITIES = [
    ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"), ("Houston", "TX"),
    ("Phoenix", "AZ"), ("Philadelphia", "PA"), ("San Antonio", "TX"), ("San Diego", "CA"),
    ("Dallas", "TX"), ("San Jose", "CA"), ("Austin", "TX"), ("Jacksonville", "FL"),
    ("San Francisco", "CA"), ("Seattle", "WA"), ("Denver", "CO"), ("Boston", "MA"),
    ("Washington", "DC"), ("Nashville", "TN"), ("Las Vegas", "NV"), ("Detroit", "MI"),
    ("Portland", "OR"), ("Memphis", "TN"), ("Louisville", "KY"), ("Atlanta", "GA"),
    ("Miami", "FL"), ("Orlando", "FL"), ("New Orleans", "LA"), ("Minneapolis", "MN"),
    ("Cleveland", "OH"), ("Pittsburgh", "PA"), ("Charlotte", "NC"), ("Salt Lake City", "UT"),
    ("Baltimore", "MD"), ("Sacramento", "CA"), ("Kansas City", "MO"), ("Indianapolis", "IN"),
    ("Columbus", "OH"), ("Milwaukee", "WI"), ("Tampa", "FL"), ("St. Louis", "MO"),
    ("Honolulu", "HI"),
]
