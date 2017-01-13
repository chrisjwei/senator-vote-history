var pg = require('pg');
pg.defaults.ssl = true;

const url = require('url')

const params = url.parse(process.env.DATABASE_URL);
const auth = params.auth.split(':');

const config = {
    user: auth[0],
    password: auth[1],
    host: params.hostname,
    port: params.port,
    database: params.pathname.split('/')[1],
    ssl: true
};

const pool = new pg.Pool(config);

var express = require('express');
var app = express();

var STATES = ['AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY']

app.set('port', (process.env.PORT || 5000));

app.use(express.static(__dirname + '/public'));

// views is directory for all template files
app.set('views', __dirname + '/views');
app.set('view engine', 'ejs');

app.get('/', function (request, response) {
    response.render('pages/index', { states: STATES })
});

app.get('/test', function(request, response){
    pool.connect(function(err, client) {
        client.query("SELECT id FROM rollcall;", function(err, result){
            if (err) {
                console.error(err); response.send("Error " + err);
            } else {
                response.send(result.rows) 
            }
        });
    });
});

app.get('/results', function (request, response) {
    state = request.param('state')
    pool.connect(function(err, client) {
        client.query("SELECT id, url, congress, session, congress_year, vote_number, to_char(vote_date, 'MM/DD/YY HH:MI AM') as vote_date, vote_title, \
                             vote_document_text, majority_requirement, vote_result, count_yea, count_nay, \
                             count_abstain, tie_breaker_whom, tie_breaker_vote, \
                             total_r_yea, total_r_nay, total_r_abstain, total_d_yea, total_d_nay, total_d_abstain, \
                             total_i_yea, total_i_nay, total_i_abstain, \
                             " + state + "0 as vote_0, " + state + "1 as vote_1 \
                             FROM rollcall \
                             ORDER BY vote_date DESC;", function(err, result_rc) {
            if (err) {
                console.error(err); response.send("Error " + err);
            }
            else {
                console.log("most recent " + result_rc.rows[0].id)
                client.query("SELECT first_name, last_name, party, bioguide_id, column_designation, \
                    address, phone, email, website \
                    FROM senator \
                    WHERE state=$1 \
                    ORDER BY column_designation ASC;", [state], function(err, result_sen){
                        if (err) {
                            console.error(err); response.send("Error " + err);
                        } else {
                            client.query("SELECT to_char(updated,'MM/DD/YY HH:MI AM') as updated FROM log LIMIT 1;", function(err, result_updated){
                                if (err) {
                                    console.error(err); response.send("Error " + err);
                                } else {
                                    console.log(result_updated.rows[0].updated)
                                    response.render('pages/results', 
                                    {
                                        results: result_rc.rows,
                                        senators: result_sen.rows,
                                        state: state,
                                        last_updated: result_updated.rows[0].updated
                                    });
                                } 
                            });
                        }
                    })
            }
        });
    });
});

app.get('/about', function(request, response){
    pool.connect(function(err, client) {
        client.query("SELECT to_char(updated,'MM/DD/YY HH:MI AM') as updated FROM log LIMIT 1;", function(err, result){
            if (err){
                console.error(err); response.send("Error " + err);
            }
            else {
                response.render('pages/about', { last_updated: result.rows[0].updated })
            } 
        });
    });
});

app.listen(app.get('port'), function() {
  console.log('Node app is running on port', app.get('port'));
});