var pg = require('pg');

var express = require('express');
var app = express();

app.set('port', (process.env.PORT || 5000));

app.use(express.static(__dirname + '/public'));

// views is directory for all template files
app.set('views', __dirname + '/views');
app.set('view engine', 'ejs');

app.get('/', function (request, response) {
    response.render('pages/index')
});

app.get('/results', function (request, response) {
    state = request.param('state')
    pg.connect(process.env.DATABASE_URL || 'postgres://postgres:password@localhost:5432/svh', function(err, client) {
        client.query("SELECT * FROM vote as v JOIN rollcall as rc on v.rollcall_id=rc.id WHERE state=$1 ORDER BY rc.vote_date DESC;", [state], function(err, result) {
            if (err) {
                console.error(err); response.send("Error " + err);
            }
            else {
                response.render('pages/results', {results: result.rows} );
            }
    });
  });
});

app.listen(app.get('port'), function() {
  console.log('Node app is running on port', app.get('port'));
});