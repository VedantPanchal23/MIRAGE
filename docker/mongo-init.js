// MongoDB initialization script for MIRAGE (runs once on fresh volume)
// Creates unprivileged application user with least-privilege readWrite role

const traceDbName = (typeof process !== "undefined" && process.env && process.env.MONGO_DB) ? process.env.MONGO_DB : "mirage_traces";
const appUser = (typeof process !== "undefined" && process.env && process.env.MONGO_APP_USER) ? process.env.MONGO_APP_USER : "mirage_app";
const appPass = (typeof process !== "undefined" && process.env && process.env.MONGO_APP_PASSWORD) ? process.env.MONGO_APP_PASSWORD : "mirage_mongo_secret";

const dbInstance = db.getSiblingDB(traceDbName);

// Check if user already exists
const existingUser = dbInstance.getUser(appUser);
if (!existingUser) {
    dbInstance.createUser({
        user: appUser,
        pwd: appPass,
        roles: [
            { role: "readWrite", db: traceDbName }
        ]
    });
    print(`Created MongoDB application user: ${appUser} on ${traceDbName}`);
} else {
    dbInstance.changeUserPassword(appUser, appPass);
    print(`MongoDB application user ${appUser} exists; credentials synchronized.`);
}
