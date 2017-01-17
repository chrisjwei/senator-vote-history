var pg = require('pg');

var ssl = true;
pg.defaults.ssl = ssl;

var Promise = require('promise');

const url = require('url')

const params = url.parse(process.env.DATABASE_URL);
const auth = params.auth.split(':');

const config = {
    user: auth[0],
    password: auth[1],
    host: params.hostname,
    port: params.port,
    database: params.pathname.split('/')[1],
    ssl: ssl,
    max: 20
};

const pool = new pg.Pool(config);

var express = require('express');
var app = express();

app.set('port', (process.env.PORT || 5000));
app.use(express.static(__dirname + '/public'));
// views is directory for all template files
app.set('views', __dirname + '/views');
app.set('view engine', 'ejs');

const STATES = ['AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
                'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD',
                'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH',
                'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
                'SD', 'TN', 'TX', 'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY']

// Routings

app.get('/', function (request, response) {
    response.render('pages/index', { states: STATES })
});

app.get('/results/:state', function(request, response){
    var state = request.params.state;
    pool.connect(function(err, client, done){
        if (err){
            console.log(err);
            response.send("Error " + err);
        } else {
            var data_promise = new Promise(function (resolve, reject) {
                client.query(
                    "SELECT id, url, congress, session, congress_year, vote_number, to_char(vote_date, 'MM/DD/YY HH:MI AM') as vote_date, vote_title, \
                     vote_document_text, majority_requirement, vote_result, count_yea, count_nay, \
                     count_abstain, tie_breaker_whom, tie_breaker_vote, \
                     total_r_yea, total_r_nay, total_r_abstain, total_d_yea, total_d_nay, total_d_abstain, \
                     total_i_yea, total_i_nay, total_i_abstain, \
                     " + state + "0 as vote_0, " + state + "1 as vote_1 \
                     FROM rollcall \
                     ORDER BY congress, session, vote_number DESC \
                     LIMIT 10;",
                    function (err, res) {
                        if (err) reject(err);
                        else resolve(res.rows);
                    });
            });
            var senator_promise = new Promise(function (resolve, reject) {
                client.query(
                    "SELECT first_name, last_name, party, bioguide_id, column_designation, address, phone, email, website \
                    FROM senator \
                    WHERE state=$1 \
                    ORDER BY column_designation ASC;", [state],
                    function (err, res) {
                        if (err) reject(err);
                        else resolve(res.rows);
                    });
            });
            var time_promise = new Promise(function (resolve, reject) {
                client.query(
                    "SELECT to_char(updated,'MM/DD/YY HH:MI AM') as updated FROM log LIMIT 1;",
                    function (err, res) {
                        if (err) resolve("Last updated could not be retrieved");
                        else resolve(res.rows[0].updated);
                    });
            });
            Promise.all([data_promise, senator_promise, time_promise])
                .then(function(res){
                    done();
                    response.render('pages/results', 
                    {
                        results: res[0],
                        senators: res[1],
                        state: state,
                        last_updated: res[2]
                    });
                })
                .catch(function(err){
                    done();
                    console.log(err);
                    response.send("Error "+ err)
                })
        }
    });
});

app.get('/about', function(request, response){
    pool.connect(function(err, client, done) {
        if (err){
            console.log(err);
            response.send("Error " + err);
        } else{
            var time_promise = new Promise(function (resolve, reject) {
                client.query(
                    "SELECT to_char(updated,'MM/DD/YY HH:MI AM') as updated FROM log LIMIT 1;",
                    function (err, res) {
                        if (err) resolve("Last updated could not be retrieved");
                        else resolve(res.rows[0].updated);
                    });
            });
            Promise.all([time_promise])
                .then(function(res){
                    done();
                    response.render('pages/about', 
                    {
                        last_updated: res[0]
                    });
                })
                .catch(function(err){
                    done();
                    console.log(err)
                    response.send("Error "+ err)
                })
        }
    });
});

app.listen(app.get('port'), function() {
  console.log('Node app is running on port', app.get('port'));
});