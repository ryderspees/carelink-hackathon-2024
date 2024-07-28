// configure express server & web socket
const express = require("express");
const app = express();
const server = require("http").createServer(app);
const axios = require("axios");

// config and dotenv
const configFile = require("./config");
const config = configFile.config;
require("dotenv").config();

// enable body parser for req body access
const bodyParser = require("body-parser");
app.use(bodyParser.urlencoded({ extended: false }));

// twilio sdk initialization
const twilio = require("twilio");
const client = require("twilio")(
  process.env.TWILIO_ACC_ID,
  process.env.AUTH_TOKEN
);

// getInfo function makes call to our flask server. The flask server uses an NLP model to
// dicipher the transcribed message and then uses esri services to geolocate the response
async function getInfo(transcript) {
  let response;
  try {
    response = await axios.post("http://localhost:5000/process", {
      text: transcript,
    });
  } catch (error) {
    console.error(error);
  }
  return response;
}

// initial route hit by twillio when a call is made
app.post("/handle-call", (req, res) => {
  const response = new twilio.twiml.VoiceResponse();
  response.say("Thank you for calling.");
  const gather = response.gather({
    action: "/transcript-complete", // Endpoint to handle user input after speech is collected
    method: "POST",
    timeout: 10, // Wait for 10 seconds of silence before ending the gathering
    speechTimeout: "auto", // Automatically handle speech timeout
    input: "speech", // Collect speech input
  });
  gather.say("Please state your location and needed services");

  res.set("Content-Type", "text/xml");
  res.send(response.toString());
});

// route hit after the transcript is completed
app.post("/transcript-complete", async (req, res) => {
  const response = new twilio.twiml.VoiceResponse();
  response.say(
    "We have received your request. Please stay on the line while we find the nearest available resource"
  );
  response.pause({ length: 1 });
  const transcript = req.body.SpeechResult; // access transcript from request body
  const flaskResponse = await getInfo(transcript);
  const address = flaskResponse.data.address;
  const type = flaskResponse.data.type_of_resource;

  response.say(`We found a ${type} at ${address}`);

  //request phone input for re-routing
  const gather = response.gather({
    numDigits: 1,
    action: "/handle-reroute", // Route to handle user input
    method: "POST",
    timeout: 10,
    input: "dtmf", // Use DTMF for keypad input
  });
  gather.say(
    "If you would like the call to be routed to their service desk, please press 1"
  );

  res.set("Content-Type", "text/xml");
  res.send(response.toString());
});

app.post("/handle-reroute", (req, res) => {
  const response = new twilio.twiml.VoiceResponse();
  const digits = req.body.Digits; // Get the digit pressed by the user

  response.say("We are rerouting you to their service desk. Have a nice day.");
  response.dial(process.env.TEAM_PHONE);

  res.set("Content-Type", "text/xml");
  res.send(response.toString());
});

server.listen(config.PORT, () => {
  console.log("listening on port 8080");
});
